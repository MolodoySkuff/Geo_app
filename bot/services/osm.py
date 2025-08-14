import os, time, requests
from shapely.geometry import shape
from ..storage.cache import get_cache_json, set_cache_json

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass.kumi.systems/api/interpreter")
USER_AGENT_EMAIL = os.getenv("USER_AGENT_EMAIL", "youremail@example.com")

# bbox = (minx, miny, maxx, maxy) в WGS84
def fetch_overpass(bbox):
    key = f"overpass_{','.join([f'{x:.5f}' for x in bbox])}"
    cached = get_cache_json(key, ttl=24*3600)
    if cached: return cached
    (minx, miny, maxx, maxy) = bbox
    # Используем out geom; включаем дороги, ЛЭП, подстанции, вода, населённые пункты, соцобъекты
    query = f"""
    [out:json][timeout:30];
    (
      way["highway"]({miny},{minx},{maxy},{maxx});
      way["power"="line"]({miny},{minx},{maxy},{maxx});
      node["power"="substation"]({miny},{minx},{maxy},{maxx});
      way["waterway"]({miny},{minx},{maxy},{maxx});
      way["natural"="water"]({miny},{minx},{maxy},{maxx});
      way["landuse"="reservoir"]({miny},{minx},{maxy},{maxx});
      node["amenity"~"school|kindergarten|clinic|hospital"]({miny},{minx},{maxy},{maxx});
      way["amenity"~"school|kindergarten|clinic|hospital"]({miny},{minx},{maxy},{maxx});
      node["public_transport"="stop_position"]({miny},{minx},{maxy},{maxx});
      node["highway"="bus_stop"]({miny},{minx},{maxy},{maxx});
      node["place"~"town|village|hamlet"]({miny},{minx},{maxy},{maxx});
    );
    out body geom;
    """
    headers = {"User-Agent": f"LandScoreBot/0.1 ({USER_AGENT_EMAIL})"}
    time.sleep(1.0)  # этика и защита от банов
    r = requests.post(OVERPASS_URL, data={"data": query}, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    set_cache_json(key, data)
    return data