import os, time, requests
from ..storage.cache import get_cache_json, set_cache_json

NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/reverse")
USER_AGENT_EMAIL = os.getenv("USER_AGENT_EMAIL", "youremail@example.com")  # укажите свой email

def reverse_geocode(lat, lon):
    key = f"nominatim_{lat:.5f}_{lon:.5f}"
    cached = get_cache_json(key, ttl=7*24*3600)
    if cached: return cached
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 14, "addressdetails": 1}
    headers = {"User-Agent": f"LandScoreBot/0.1 ({USER_AGENT_EMAIL})"}
    time.sleep(1.0)  # соблюдаем политику
    r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    set_cache_json(key, data)
    return data