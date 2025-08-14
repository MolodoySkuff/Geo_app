import json, math, os
from typing import Tuple
from shapely.geometry import shape, Polygon, MultiPolygon, Point, mapping, LineString
from shapely.ops import unary_union
from shapely.affinity import rotate
from shapely.ops import transform
from pyproj import Transformer, CRS
import numpy as np

ROAD_TAGS_MAJOR = {"motorway","trunk","primary","secondary"}
ROAD_TAGS_ALL = ROAD_TAGS_MAJOR | {"tertiary","unclassified","residential","service"}

def read_polygon_from_file(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext.endswith("json") or ext.endswith("geojson"):
        with open(path, "r", encoding="utf-8") as f:
            gj = json.load(f)
        g = gj.get("geometry", gj)
        poly = shape(g)
        if not isinstance(poly, (Polygon, MultiPolygon)):
            raise ValueError("GeoJSON не Polygon/MultiPolygon")
        return poly
    elif ext.endswith("kml"):
        return _read_kml_polygon(path)
    else:
        raise ValueError("Поддерживаются только GeoJSON/KML")

def _read_kml_polygon(path: str):
    # Мини‑парсер KML: берём первый Polygon coordinates
    import xml.etree.ElementTree as ET
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    tree = ET.parse(path)
    root = tree.getroot()
    coords = None
    for elem in root.findall(".//kml:Polygon//kml:outerBoundaryIs//kml:LinearRing//kml:coordinates", ns):
        coords = elem.text.strip()
        break
    if not coords:
        raise ValueError("Polygon не найден в KML")
    pts = []
    for t in coords.replace("\n"," ").split():
        parts = t.split(",")
        if len(parts) >= 2:
            lon, lat = float(parts[0]), float(parts[1])
            pts.append((lon, lat))
    if len(pts) < 3:
        raise ValueError("Слишком мало точек в KML")
    return Polygon(pts)

def _utm_crs_for(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)

def project_to_utm(geom_wgs84):
    lon, lat = geom_wgs84.centroid.x, geom_wgs84.centroid.y
    crs_utm = _utm_crs_for(lon, lat)
    to_utm = Transformer.from_crs("EPSG:4326", crs_utm, always_xy=True).transform
    to_wgs = Transformer.from_crs(crs_utm, "EPSG:4326", always_xy=True).transform
    return transform(to_utm, geom_wgs84), to_utm, to_wgs, crs_utm

def expand_bbox(bbox_wgs84, meters=2000):
    (minx, miny, maxx, maxy) = bbox_wgs84
    # Небольшая грубая аппроксимация: 1 deg lat ≈ 111 км, 1 deg lon ≈ 111*cos(lat)
    lat = (miny + maxy) / 2.0
    dlat = meters / 111_000.0
    dlon = meters / (111_000.0 * max(math.cos(math.radians(lat)), 0.1))
    return (minx - dlon, miny - dlat, maxx + dlon, maxy + dlat)

def _collect_geoms(overpass_data, filter_fn):
    geoms = []
    for el in overpass_data.get("elements", []):
        tags = el.get("tags", {})
        if not filter_fn(tags, el["type"]):
            continue
        # el may contain "geometry" with list of dicts {lat, lon}; or be node with lat/lon
        if "geometry" in el:
            coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
            if el["type"] == "way":
                # Heuristics: ways with area-like tags to polygon, else line
                if tags.get("area") == "yes" or tags.get("natural")=="water" or tags.get("landuse")=="reservoir":
                    try:
                        geoms.append(Polygon(coords))
                    except Exception:
                        pass
                else:
                    geoms.append(LineString(coords))
        elif el["type"] == "node":
            geoms.append(Point(el["lon"], el["lat"]))
    return geoms

def compute_all(geom_wgs84, osm_data, dem_stats):
    parcel_utm, to_utm, to_wgs, crs_utm = project_to_utm(geom_wgs84)
    area_m2 = parcel_utm.area
    area_ha = area_m2 / 10_000.0

    roads_major = _collect_geoms(osm_data, lambda t, typ: t.get("highway") in ROAD_TAGS_MAJOR and typ=="way")
    roads_all = _collect_geoms(osm_data, lambda t, typ: t.get("highway") in ROAD_TAGS_ALL and typ=="way")
    waters = _collect_geoms(osm_data, lambda t, typ: (t.get("waterway") or t.get("natural")=="water" or t.get("landuse")=="reservoir"))
    powers = _collect_geoms(osm_data, lambda t, typ: t.get("power")=="line")
    subst = _collect_geoms(osm_data, lambda t, typ: t.get("power")=="substation")
    stops = _collect_geoms(osm_data, lambda t, typ: (t.get("highway")=="bus_stop" or t.get("public_transport")=="stop_position"))
    socials = _collect_geoms(osm_data, lambda t, typ: t.get("amenity") in ("school","kindergarten","clinic","hospital"))
    places = _collect_geoms(osm_data, lambda t, typ: t.get("place") in ("town","village","hamlet"))

    # Проецируем все в UTM
    def proj_list(lst): 
        return [transform(to_utm, g) for g in lst]
    r_major_u = proj_list(roads_major)
    r_all_u = proj_list(roads_all)
    waters_u = proj_list(waters)
    powers_u = proj_list(powers)
    subst_u = proj_list(subst)
    stops_u = proj_list(stops)
    socials_u = proj_list(socials)
    places_u = proj_list(places)

    def min_distance(geom, candidates):
        if not candidates: return None
        u = unary_union(candidates)
        d = geom.distance(u)
        return float(d)

    d_road = min_distance(parcel_utm, r_major_u) or min_distance(parcel_utm, r_all_u)
    d_water = min_distance(parcel_utm, waters_u)
    d_power = min_distance(parcel_utm, powers_u)
    d_stop = min_distance(parcel_utm, stops_u)
    d_place = min_distance(parcel_utm, places_u)

    # Касание дороги и “фасад”: длина границы участка в 10 м буфере от дорог
    facade_len_m = 0.0
    touches_road = False
    if r_all_u:
        roads_buf = unary_union([g.buffer(10) for g in r_all_u])
        boundary = parcel_utm.boundary
        inter = boundary.intersection(roads_buf)
        facade_len_m = float(inter.length) if not inter.is_empty else 0.0
        touches_road = facade_len_m > 0.5

    # “Дом 10×10”: проверка на минимальный охватывающий прямоугольник
    mrr = parcel_utm.minimum_rotated_rectangle
    coords = list(mrr.exterior.coords)
    edges = [math.dist(coords[i], coords[(i+1)%4]) for i in range(4)]
    width, height = sorted(edges)[:2]
    can_house_10x10 = (width >= 10 and height >= 10)

    # Индикативный flood: низинность + близость к воде
    flood_risk = 0.0
    rel_low = dem_stats.get("rel_lowness_m", 0.0)
    if rel_low < -1.5:
        flood_risk += min(1.0, abs(rel_low)/3.0)  # до 1.0
    if d_water is not None:
        flood_risk += max(0.0, (50 - min(d_water, 50))/50.0) * 0.7  # ближе 50м — высокий риск
    flood_risk = float(max(0.0, min(flood_risk, 1.0)))

    # Нормировка и итоговый скор (0–100)
    def norm_inv_dist(d, good, bad):
        if d is None: return 30
        if d <= good: return 100
        if d >= bad: return 0
        return 100 * (bad - d) / (bad - good)

    score_access = norm_inv_dist(d_road or 5000, 300, 5000)
    slope_pct = dem_stats.get("slope_indicative_pct", 5.0)
    score_slope = max(0, 100 - min(100, abs(slope_pct - 3) * 15))  # лучше около 0–5%
    score_flood = 100 - int(flood_risk * 100)
    score_infra = norm_inv_dist(d_stop or 4000, 500, 4000)
    score_power = norm_inv_dist(d_power or 5000, 300, 5000)

    # Веса для ИЖС по умолчанию
    score_total = round(
        0.25*score_access + 0.20*score_flood + 0.20*score_slope +
        0.15*score_infra + 0.10*score_power + 0.10*(100 if touches_road else 40)
    )

    return {
        "area_m2": area_m2,
        "area_ha": area_ha,
        "touches_road": touches_road,
        "facade_len_m": facade_len_m,
        "can_house_10x10": can_house_10x10,
        "d_road_m": d_road,
        "d_water_m": d_water,
        "d_power_m": d_power,
        "d_stop_m": d_stop,
        "d_place_m": d_place,
        "dem": dem_stats,
        "score": {
            "access": score_access,
            "flood": score_flood,
            "slope": score_slope,
            "infra": score_infra,
            "power": score_power,
            "total": int(score_total)
        }
    }

def square_from_point_area(lat, lon, area_sot):
    area_m2 = area_sot * 100.0  # 1 сотка = 100 м2
    side = math.sqrt(area_m2)
    center = Point(lon, lat)
    poly_utm, to_utm, to_wgs, crs = project_to_utm(center.buffer(1))
    c = transform(to_utm, center)
    s = side / 2.0
    rect = Polygon([(c.x - s, c.y - s), (c.x + s, c.y - s), (c.x + s, c.y + s), (c.x - s, c.y + s)])
    rect_wgs = transform(Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform, rect)
    return rect_wgs

def format_brief(metric_set, addr):
    loc = addr.get("display_name", "нет адреса")
    area = metric_set["area_ha"]
    t = metric_set["score"]["total"]
    road = metric_set.get("d_road_m")
    water = metric_set.get("d_water_m")
    flood = metric_set["score"]["flood"]
    s = metric_set["score"]["slope"]
    touch = "Да" if metric_set["touches_road"] else "Нет"
    house = "Да" if metric_set["can_house_10x10"] else "Сомнительно"
    return (
        f"📍 {loc}\n"
        f"Площадь: {area:.2f} га\n"
        f"Скоринг: <b>{t}/100</b> (доступ {metric_set['score']['access']:.0f}, уклон {s:.0f}, "
        f"вода {flood:.0f}, инфра {metric_set['score']['infra']:.0f})\n"
        f"Дорога: {int(road) if road else '—'} м | Вода: {int(water) if water else '—'} м | "
        f"Касание дороги: {touch} | Дом 10×10: {house}"
    )