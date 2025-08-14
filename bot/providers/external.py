# Заглушка под внешнего провайдера КН→контур.
# Имплементируйте get_geometry_by_cadnum и верните shapely Polygon в EPSG:4326 или None.
from shapely.geometry import Polygon

def get_geometry_by_cadnum(cadnum: str):
    # TODO: подключите SDK/REST вашего провайдера
    # пример:
    # geom = provider.get(cadnum) → [(lon,lat), ...]
    # return Polygon(coords) if coords else None
    return None