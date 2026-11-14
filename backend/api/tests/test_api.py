import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import db
from app.main import app
from app.models import Device, User
from app.security import hash_device_key, hash_password

KEY = "test-device-key"
NOW = int(time.time() * 1000)


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.set_engine(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Device(dev="har01", alias="Ông A", key_hash=hash_device_key(KEY)))
        s.add(Device(dev="har02", key_hash=hash_device_key("other")))
        s.add(User(email="gv@test.vn", password_hash=hash_password("matkhau123"), role="viewer"))
        s.commit()
    with TestClient(app) as c:
        yield c


def _login(c) -> dict:
    r = c.post("/api/auth/login", json={"email": "gv@test.vn", "password": "matkhau123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


DEV = {"X-Device-Key": KEY}


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_auth_required(client):
    for path in ["/api/status", "/api/events", "/api/metrics", "/api/segments?dev=har01", "/api/summary?dev=har01"]:
        assert client.get(path).status_code == 401, path
    assert client.post("/api/ingest/status", json={"dev": "har01", "t": NOW}).status_code == 401
    assert client.post("/api/ingest/status", json={"dev": "har01", "t": NOW}, headers={"X-Device-Key": "sai"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "gv@test.vn", "password": "sai"}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_device_cannot_write_other_device(client):
    r = client.post("/api/ingest/status", json={"dev": "har02", "t": NOW}, headers=DEV)
    assert r.status_code == 403


def test_status_roundtrip(client):
    body = {"dev": "har01", "t": NOW, "label": "walk", "conf": 0.9, "battery_v": 3.9, "battery_pct": 70,
            "temp_c": 29.1, "rh": 70, "rssi": -55, "model": "rf-imu+baro-v1", "fw": "0.2.0"}
    assert client.post("/api/ingest/status", json=body, headers=DEV).status_code == 200
    body2 = {**body, "t": NOW + 5000, "label": "sit"}
    assert client.post("/api/ingest/status", json=body2, headers=DEV).status_code == 200
    h = _login(client)
    st = client.get("/api/status", headers=h).json()
    assert len(st) == 1 and st[0]["label"] == "sit" and st[0]["online"] is True and st[0]["alias"] == "Ông A"
    # status_log chỉ ghi 1 dòng/phút
    hist = client.get(f"/api/status/history?dev=har01&from={NOW - 1000}&to={NOW + 10000}", headers=h).json()
    assert len(hist) == 1
    devices = client.get("/api/devices", headers=h).json()
    assert {d["dev"]: d["model"] for d in devices}["har01"] == "rf-imu+baro-v1"
    assert "key_hash" not in devices[0]


def test_segments_dedup_and_summary(client):
    segs = [
        {"dev": "har01", "start": NOW - 60_000, "end": NOW - 30_000, "label": "walk", "conf_avg": 0.9},
        {"dev": "har01", "start": NOW - 30_000, "end": NOW, "label": "sit", "conf_avg": 0.8},
    ]
    r1 = client.post("/api/ingest/segments", json={"segments": segs}, headers=DEV).json()
    r2 = client.post("/api/ingest/segments", json={"segments": segs}, headers=DEV).json()
    assert r1["inserted"] == 2 and r2["inserted"] == 0
    h = _login(client)
    got = client.get(f"/api/segments?dev=har01&from={NOW - 3600_000}&to={NOW + 1}", headers=h).json()
    assert [s["label"] for s in got] == ["walk", "sit"]
    summ = client.get("/api/summary?dev=har01&days=7", headers=h).json()
    assert len(summ) == 7
    total = sum(sum(d["seconds"].values()) for d in summ)
    assert abs(total - 60) < 0.01


def test_events_dedup_update_and_ack(client):
    ev = {"id": "har01-1", "dev": "har01", "t": NOW, "type": "fall", "severity": "high", "source": "both", "prob": 0.9}
    r = client.post("/api/ingest/events", json={"events": [ev]}, headers=DEV).json()
    assert r["new"] == 1
    h = _login(client)
    assert client.patch("/api/events/har01-1", json={"acknowledged": True}, headers=h).json()["acknowledged_by"] == "gv@test.vn"
    # gửi lại cùng id với cờ hủy: cập nhật nhưng giữ "đã xử lý"
    r = client.post("/api/ingest/events", json={"events": [{**ev, "cancelled": True}]}, headers=DEV).json()
    assert r["new"] == 0
    evs = client.get("/api/events?dev=har01", headers=h).json()
    assert len(evs) == 1 and evs[0]["cancelled"] is True and evs[0]["acknowledged"] is True
    assert client.patch("/api/events/khong-co", json={}, headers=h).status_code == 404


def test_metrics_upsert(client):
    m = {"experiment": "A1", "model": "rf-imu-v1", "features": "imu", "window_s": 2.5, "accuracy": 0.9,
         "macro_f1": 0.85, "f1_per_class": {"walk": 0.9}, "confusion": {"labels": ["walk"], "matrix": [[10]]},
         "n_windows": 100, "n_subjects": 5}
    assert client.post("/api/ingest/metrics", json=m, headers=DEV).status_code == 200
    assert client.post("/api/ingest/metrics", json={**m, "macro_f1": 0.87}, headers=DEV).status_code == 200
    sm = {"items": [{"dev": "har01", "day": "2026-11-14", "latency": {"device_pi": {"median": 40, "p95": 90}}, "packet_loss": 0.002}]}
    assert client.post("/api/ingest/system_metrics", json=sm, headers=DEV).status_code == 200
    out = client.get("/api/metrics", headers=_login(client)).json()
    assert len(out["experiments"]) == 1 and out["experiments"][0]["macro_f1"] == 0.87
    assert out["system"][0]["packet_loss"] == 0.002


def test_websocket_receives_event(client):
    token = _login(client)["Authorization"].split()[1]
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ev = {"id": "har01-2", "dev": "har01", "t": NOW, "type": "sos", "severity": "high", "source": "device"}
        client.post("/api/ingest/events", json={"events": [ev]}, headers=DEV)
        msg = ws.receive_json()
        assert msg["type"] == "event" and msg["data"]["id"] == "har01-2" and msg["data"]["new"] is True


def test_websocket_rejects_without_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
