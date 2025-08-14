import numpy as np
import srtm
from shapely.geometry import Polygon, Point
from shapely.ops import transform
from pyproj import Transformer, CRS
from . import metrics as mutils

_elev = srtm.get_data()

def _utm_crs_for(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)

def compute_dem_stats(geom_wgs84, step_m=30.0, buffer_m=200):
    # Буфер для относительной низинности
    lon, lat = geom_wgs84.centroid.x, geom_wgs84.centroid.y
    crs_utm = _utm_crs_for(lon, lat)
    to_utm = Transformer.from_crs("EPSG:4326", crs_utm, always_xy=True).transform
    to_wgs = Transformer.from_crs(crs_utm, "EPSG:4326", always_xy=True).transform

    g_utm = transform(to_utm, geom_wgs84).buffer(buffer_m)
    minx, miny, maxx, maxy = g_utm.bounds
    # Шаг в градусах оценим после обратной трансформации — здесь проще сэмплировать равномерную сетку в UTM и конвертить в WGS
    nx = max(5, int((maxx - minx) / step_m))
    ny = max(5, int((maxy - miny) / step_m))
    xs = np.linspace(minx, maxx, nx)
    ys = np.linspace(miny, maxy, ny)

    elev = []
    elev_in = []
    for x in xs:
        for y in ys:
            pt_utm = Point(x, y)
            if not g_utm.contains(pt_utm):
                continue
            lon2, lat2 = transform(to_wgs, pt_utm).x, transform(to_wgs, pt_utm).y
            h = _elev.get_elevation(lat2, lon2)
            if h is None:
                continue
            elev.append(h)
            if transform(to_utm, geom_wgs84).contains(pt_utm):
                elev_in.append(h)
    if not elev_in:  # fallback — пробуем хотя бы центроид
        h0 = _elev.get_elevation(lat, lon)
        elev_in = [h0] if h0 is not None else [0]

    elev = np.array(elev) if elev else np.array(elev_in)
    elev_in = np.array(elev_in)
    # Уклон: оценим по градиенту на внутренней сетке
    # Примитивно: возьмём 3x3 окрестности — упростим до std перепада на шаг
    slope_pct = float(np.clip(np.std(np.diff(np.sort(elev_in))) if len(elev_in) > 3 else 0.0, 0, 100))  # очень грубо
    stats = {
        "elev_min": float(np.min(elev_in)),
        "elev_max": float(np.max(elev_in)),
        "elev_med": float(np.median(elev_in)),
        "elev_p95": float(np.percentile(elev_in, 95)),
        "slope_indicative_pct": slope_pct,
        "rel_lowness_m": float(np.median(elev_in) - float(np.median(elev))),  # <0 → низина
    }
    return stats