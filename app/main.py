import os
import threading
import time
from collections import Counter, deque

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter as PromCounter, generate_latest

try:
    import geoip2.database
except ImportError:
    geoip2 = None

app = FastAPI(title="ipecho", version="0.4.0")

BUILD_INFO = {
    "version": os.getenv("APP_VERSION", "0.4.0"),
    "git_sha": os.getenv("GIT_SHA", "dev"),
    "build_time": os.getenv("BUILD_TIME", "unknown"),
}

_lock = threading.Lock()
_locations = {}
_recent = deque(maxlen=100)
_country_counts = Counter()

requests_total = PromCounter("ipecho_requests_total", "Total requests seen", ["country"])

TRUSTED_IP_HEADERS = ("cf-connecting-ip", "true-client-ip")


def _open_reader():
    path = os.getenv("GEOIP_DB", "")
    if geoip2 and path and os.path.exists(path):
        try:
            return geoip2.database.Reader(path)
        except Exception:
            return None
    return None


_geoip_reader = _open_reader()


def client_ip(request: Request) -> str:
    for header in TRUSTED_IP_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    if request.client:
        return request.client.host
    return "unknown"


def geolocate(ip: str, request: Request):
    country = request.headers.get("cf-ipcountry", "").upper()
    city = None
    lat = None
    lon = None
    if _geoip_reader:
        try:
            r = _geoip_reader.city(ip)
            country = (r.country.iso_code or country or "").upper()
            city = r.city.name
            lat = r.location.latitude
            lon = r.location.longitude
        except Exception:
            pass
    if not country or country in ("XX", "T1"):
        country = "ZZ"
    return country, city, lat, lon


def record(ip: str, country: str, city, lat, lon) -> None:
    ts = int(time.time())
    with _lock:
        _country_counts[country] += 1
        _recent.appendleft({"ip": ip, "country": country, "city": city, "lat": lat, "lon": lon, "ts": ts})
        if lat is not None and lon is not None:
            key = (round(lat, 2), round(lon, 2))
            loc = _locations.get(key)
            if loc:
                loc["count"] += 1
            else:
                _locations[key] = {"lat": lat, "lon": lon, "country": country, "city": city, "count": 1}
    requests_total.labels(country=country).inc()


@app.get("/")
async def root(request: Request):
    ip = client_ip(request)
    country, city, lat, lon = geolocate(ip, request)
    record(ip, country, city, lat, lon)
    if "text/plain" in request.headers.get("accept", ""):
        return PlainTextResponse(ip + "\n")
    return {
        "ip": ip,
        "country": country,
        "city": city,
        "lat": lat,
        "lon": lon,
        "hostname": os.getenv("HOSTNAME", "unknown"),
        "forwarded_for": request.headers.get("x-forwarded-for"),
    }


@app.get("/myip", response_class=PlainTextResponse)
async def myip(request: Request):
    ip = client_ip(request)
    country, city, lat, lon = geolocate(ip, request)
    record(ip, country, city, lat, lon)
    return ip + "\n"


@app.get("/version")
async def version():
    return BUILD_INFO


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/stats")
async def stats():
    with _lock:
        return list(_locations.values())


@app.get("/log")
async def log():
    with _lock:
        return list(_recent)


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
