import os, json, time, hashlib

CACHE_DIR = os.getenv("CACHE_DIR", "./cache")
TILE_CACHE_DIR = os.getenv("TILE_CACHE_DIR", "./cache/tiles")

def ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(TILE_CACHE_DIR, exist_ok=True)
    os.makedirs(os.path.join(CACHE_DIR, "uploads"), exist_ok=True)

def _path_for(key: str):
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")

def get_cache_json(key: str, ttl: int):
    path = _path_for(key)
    try:
        st = os.stat(path)
        if time.time() - st.st_mtime > ttl:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def set_cache_json(key: str, data):
    path = _path_for(key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)