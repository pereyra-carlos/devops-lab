from fastapi.testclient import TestClient

import main
from main import app, geolocate

client = TestClient(app)


class FakeRequest:
    def __init__(self, headers):
        self.headers = headers


def setup_function():
    main._country_counts.clear()
    main._recent.clear()
    main._locations.clear()
    main._ci_cache.update({"data": [], "ts": 0})


def test_root_returns_ip():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ip" in resp.json()


def test_root_prefers_forwarded_for():
    resp = client.get("/", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
    assert resp.json()["ip"] == "203.0.113.7"


def test_root_prefers_cf_connecting_ip_over_forwarded_for():
    resp = client.get("/", headers={"CF-Connecting-IP": "198.51.100.9", "X-Forwarded-For": "10.42.0.0"})
    assert resp.json()["ip"] == "198.51.100.9"


def test_myip_returns_plain_ip():
    resp = client.get("/myip", headers={"CF-Connecting-IP": "203.0.113.5"})
    assert resp.text.strip() == "203.0.113.5"
    assert "text/plain" in resp.headers["content-type"]


def test_version_has_build_info():
    body = client.get("/version").json()
    assert "version" in body and "git_sha" in body and "build_time" in body


def test_geolocate_fallback_country_from_header():
    country, city, lat, lon = geolocate("203.0.113.7", FakeRequest({"cf-ipcountry": "ar"}))
    assert country == "AR"
    assert lat is None and lon is None


def test_geolocate_unknown_defaults_zz():
    country, _, _, _ = geolocate("10.0.0.1", FakeRequest({"cf-ipcountry": "XX"}))
    assert country == "ZZ"


def test_root_plain_text():
    resp = client.get("/", headers={"Accept": "text/plain", "X-Forwarded-For": "192.0.2.1"})
    assert resp.text.strip() == "192.0.2.1"


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_ready():
    assert client.get("/ready").json()["status"] == "ready"


def test_stats_is_list():
    assert isinstance(client.get("/stats").json(), list)


def test_stats_aggregates_points():
    main.record("1.1.1.1", "AR", "Cordoba", -31.4, -64.2)
    main.record("2.2.2.2", "AR", "Cordoba", -31.4, -64.2)
    main.record("3.3.3.3", "UY", "Montevideo", -34.9, -56.2)
    points = {(p["lat"], p["lon"]): p["count"] for p in client.get("/stats").json()}
    assert points[(-31.4, -64.2)] == 2
    assert points[(-34.9, -56.2)] == 1


def test_stats_includes_ips_per_point():
    main.record("9.9.9.9", "US", "St Louis", 10.0, 20.0)
    main.record("8.8.8.8", "US", "St Louis", 10.0, 20.0)
    row = [p for p in client.get("/stats").json() if p["lat"] == 10.0][0]
    assert "9.9.9.9" in row["ips"] and "8.8.8.8" in row["ips"]


def test_log_keeps_recent():
    client.get("/", headers={"X-Forwarded-For": "203.0.113.1"})
    entries = client.get("/log").json()
    assert entries[0]["ip"] == "203.0.113.1"


def test_ci_returns_cached_runs():
    main._ci_cache.update({"data": [{"run_number": 1, "conclusion": "success"}], "ts": 9_999_999_999})
    resp = client.get("/ci")
    assert resp.status_code == 200
    assert resp.json()[0]["conclusion"] == "success"


def test_metrics_exposes_counter():
    client.get("/", headers={"CF-IPCountry": "AR"})
    assert "ipecho_requests_total" in client.get("/metrics").text
