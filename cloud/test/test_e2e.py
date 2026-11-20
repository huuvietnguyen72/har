"""Kiểm tra HAR cloud (Worker + D1) từ đầu tới cuối, gồm cả lớp HttpPublisher mà Pi (har-uplink) đang dùng.

Chạy với Worker trên máy:
    cd cloud && npx wrangler dev --local --port 8787
    CLOUD_URL=http://127.0.0.1:8787 CLOUD_DEVICE_KEY=... CLOUD_EMAIL=... CLOUD_PASSWORD=... \
        ../edge/.venv/Scripts/python -m pytest -q test/test_e2e.py
Dùng D1 trống (mỗi lần chạy tạo id/thời điểm mới nên chạy lại được).
"""
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "edge"))
from har_edge.publisher import HttpPublisher, RejectedError  # noqa: E402

URL = os.environ.get("CLOUD_URL", "http://127.0.0.1:8787").rstrip("/")
KEY = os.environ.get("CLOUD_DEVICE_KEY", "")
EMAIL = os.environ.get("CLOUD_EMAIL", "")
PASSWORD = os.environ.get("CLOUD_PASSWORD", "")
NOW = int(time.time() * 1000)
RUN = str(NOW)

pytestmark = pytest.mark.skipif(not (KEY and EMAIL and PASSWORD), reason="cần CLOUD_DEVICE_KEY, CLOUD_EMAIL, CLOUD_PASSWORD")


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=URL, timeout=15) as c:
        yield c


@pytest.fixture(scope="module")
def auth(http):
    r = http.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["email"] == EMAIL.lower() and body["expires_at"] > NOW
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.fixture(scope="module")
def pub():
    p = HttpPublisher(URL + "/api", KEY)
    yield p
    p.close()


def test_health_and_web_app(http):
    assert http.get("/api/health").json()["ok"] is True
    for path in ("/", "/history", "/alerts"):  # SPA: mọi đường không phải /api trả index.html
        r = http.get(path)
        assert r.status_code == 200 and "<div id=\"root\">" in r.text, path


def test_auth_required_and_wrong_password(http):
    for path in ["/api/status", "/api/events", "/api/metrics", "/api/segments?dev=har01", "/api/summary?dev=har01", "/api/devices"]:
        assert http.get(path).status_code == 401, path
    assert http.get("/api/status", headers={"Authorization": "Bearer x.y.z"}).status_code == 401
    assert http.post("/api/auth/login", json={"email": EMAIL, "password": "sai-mat-khau"}).status_code == 401
    assert http.post("/api/ingest/status", json={"dev": "har01", "t": NOW}).status_code == 401
    assert http.post("/api/ingest/status", json={"dev": "har01", "t": NOW}, headers={"X-Device-Key": "sai"}).status_code == 401


def test_device_cannot_write_other_device(http):
    r = http.post("/api/ingest/status", json={"dev": "har02", "t": NOW}, headers={"X-Device-Key": KEY})
    assert r.status_code == 403


def test_status_roundtrip_via_pi_publisher(pub, http, auth):
    body = {"v": 1, "dev": "har01", "t": NOW, "label": "walk", "conf": 0.9, "online": True, "battery_v": None,
            "battery_pct": None, "temp_c": 29.1, "rh": 70.0, "rssi": -55, "model": "rf-imu+baro-2.5s-v4", "fw": "1.0.0"}
    assert pub.publish_status(body)["ok"] is True
    st = [s for s in http.get("/api/status", headers=auth).json() if s["dev"] == "har01"][0]
    assert st["label"] == "walk" and st["online"] is True and st["model"] == "rf-imu+baro-2.5s-v4" and st["fw"] == "1.0.0"
    devs = http.get("/api/devices", headers=auth).json()
    assert devs[0]["dev"] == "har01" and "key_hash" not in devs[0]
    hist = http.get("/api/status/history", params={"dev": "har01", "from": NOW - 1000, "to": NOW + 1000}, headers=auth).json()
    assert len(hist) >= 1 and hist[-1]["temp_c"] == 29.1 and hist[-1]["online"] is True


def test_segments_dedup_and_summary(pub, http, auth):
    t0 = NOW - 3_600_000
    segs = [{"dev": "har01", "start": t0, "end": t0 + 60_000, "label": "walk", "conf_avg": 0.9},
            {"dev": "har01", "start": t0 + 60_000, "end": t0 + 90_000, "label": "sit", "conf_avg": 0.8}]
    assert pub.publish_segments(segs)["inserted"] == 2
    assert pub.publish_segments(segs)["inserted"] == 0  # Pi gửi lại outbox: không trùng
    got = http.get("/api/segments", params={"dev": "har01", "from": t0, "to": t0 + 100_000}, headers=auth).json()
    assert [s["label"] for s in got] == ["walk", "sit"] and got[0]["end"] == t0 + 60_000
    day = time.strftime("%Y-%m-%d", time.gmtime((t0 + 7 * 3600_000) / 1000))  # ngày theo giờ Việt Nam
    summ = http.get("/api/summary", params={"dev": "har01", "day": day}, headers=auth).json()
    assert summ[0]["day"] == day and summ[0]["seconds"]["walk"] >= 60 and summ[0]["seconds"]["sit"] >= 30
    assert len(http.get("/api/summary", params={"dev": "har01", "days": 7}, headers=auth).json()) == 7
    with pytest.raises(RejectedError):  # end < start: Pi bỏ, không gửi lại mãi
        pub.publish_segments([{"dev": "har01", "start": NOW, "end": NOW - 1, "label": "walk"}])


def test_events_dedup_update_and_ack(pub, http, auth):
    ev = {"id": f"har01-{RUN}", "dev": "har01", "t": NOW, "type": "fall", "severity": "high", "source": "both", "prob": 0.9,
          "prev_label": "walk", "battery_pct": None, "cancelled": False, "delivered_late": False}
    assert pub.publish_events([ev])["new"] == 1
    r = http.patch(f"/api/events/{ev['id']}", json={"acknowledged": True}, headers=auth).json()
    assert r["acknowledged"] is True and r["acknowledged_by"] == EMAIL.lower() and r["acknowledged_at"]
    assert pub.publish_events([{**ev, "cancelled": True}])["new"] == 0  # gửi lại cùng id: cập nhật, giữ cờ đã xử lý
    got = [e for e in http.get("/api/events", params={"dev": "har01"}, headers=auth).json() if e["id"] == ev["id"]][0]
    assert got["cancelled"] is True and got["acknowledged"] is True
    assert http.patch("/api/events/khong-co", json={"acknowledged": True}, headers=auth).status_code == 404
    with pytest.raises(RejectedError):
        pub.publish_events([{**ev, "id": f"x-{RUN}", "type": "nhay"}])


def test_metrics_and_system_metrics(pub, http, auth):
    m = {"experiment": f"T{RUN[-6:]}", "model": "rf-imu+baro-2.5s-v4", "features": "imu+baro", "window_s": 2.5,
         "accuracy": 0.93, "macro_f1": 0.89, "f1_per_class": {"walk": 0.93}, "confusion": {"labels": ["walk"], "matrix": [[10]]},
         "n_windows": 4047, "n_subjects": 4, "extra": {"align_upright": True}}
    assert pub.publish_metrics(m)["ok"] is True
    assert pub.publish_metrics({**m, "macro_f1": 0.9})["ok"] is True  # cùng thí nghiệm: ghi đè
    pub.publish_system_metrics([{"dev": "har01", "day": "2026-11-20", "latency": {"device_pi": {"median": 21, "p95": 40, "n": 507}},
                                 "packet_loss": 0.0, "packets": 10047}])
    out = http.get("/api/metrics", headers=auth).json()
    exp = [e for e in out["experiments"] if e["experiment"] == m["experiment"]][0]
    assert exp["macro_f1"] == 0.9 and exp["f1_per_class"] == {"walk": 0.93} and exp["extra"]["align_upright"] is True
    sysm = [s for s in out["system"] if s["day"] == "2026-11-20"][0]
    assert sysm["latency"]["device_pi"]["median"] == 21 and out["running_models"]["har01"] == "rf-imu+baro-2.5s-v4"


def test_validation_errors(http, auth):
    h = {"X-Device-Key": KEY}
    assert http.post("/api/ingest/status", json={"dev": "har01"}, headers=h).status_code == 422  # thiếu t
    assert http.post("/api/ingest/status", json={"dev": "har01", "t": NOW, "conf": 2}, headers=h).status_code == 422
    assert http.get("/api/events", params={"limit": 5000}, headers=auth).status_code == 422
    assert http.get("/api/segments", params={"dev": "har01", "from": 0, "to": NOW}, headers=auth).status_code == 422  # > 8 ngày
    assert http.get("/api/segments", headers=auth).status_code == 422  # thiếu dev
