import os, uuid
from staticmap import StaticMap, CircleMarker, Polygon as SMPolygon, Line
from shapely.geometry import mapping
from shapely.ops import transform
from pyproj import Transformer

def _extract_ring_coords(geom):
    # Возвращает один внешний контур координат
    g = geom
    if g.geom_type == "MultiPolygon":
        g = list(g.geoms)[0]
    return list(g.exterior.coords)

def render_static_map(geom_wgs84, osm_data, out_dir="cache/maps"):
    os.makedirs(out_dir, exist_ok=True)
    m = StaticMap(800, 600, url_template="https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
    # Участок
    coords = _extract_ring_coords(geom_wgs84)
    poly = SMPolygon(coords, fill_color="#3388ff80", outline_color="#1f78b4", width=2)
    m.add_polygon(poly)
    # Простейшая дорога рядом (визуально)
    for el in osm_data.get("elements", [])[:500]:
        if el.get("type")=="way" and el.get("tags",{}).get("highway"):
            if "geometry" in el:
                line = [(p["lon"], p["lat"]) for p in el["geometry"]]
                m.add_line(Line(line, "#444444", 1))
    image = m.render(zoom=None)  # авто‑зум по слоям
    path = os.path.join(out_dir, f"map_{uuid.uuid4().hex}.png")
    image.save(path)
    return path