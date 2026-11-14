import json

import httpx
import numpy as np
import pytest

from har_edge import store
from har_edge.config import Config
from har_edge.fall_threshold import detect_all
from har_edge.features import FEATURE_NAMES_BARO, FEATURE_NAMES_IMU, cnn_input, extract_features
from har_edge.infer import Infer
from har_edge.ingest import Ingest
from har_edge.logic import FallFusion, Segmenter, Smoother, TechMonitor
from har_edge.model import HeuristicModel
from har_edge.notify import Notifier, format_message
from har_edge.publisher import ConsolePublisher, HttpPublisher, PublishError
from har_edge.synth import generate
from har_edge.units import ACC_LSB_PER_G, battery_pct, imu_packet_to_array, to_raw_acc, to_raw_gyro
from har_edge.uplink import Uplink, compute_system_metrics

RNG = np.random.default_rng(0)
T0 = 1_763_060_000_000


@pytest.fixture()
def conn(tmp_path):
    return store.connect(tmp_path / "edge.db")


def packets(acc, gyr, pres, t0=T0, seq0=0, dev="har01"):
    """Đổi tín hiệu thành chuỗi gói MQTT giống ESP32."""
    out = []
    for k, i in enumerate(range(0, len(acc) - 24, 25)):
        ra, rg = to_raw_acc(acc[i:i + 25]), to_raw_gyro(gyr[i:i + 25])
        t = t0 + i * 20
        out.append((f"har/{dev}/imu", {"v": 1, "seq": seq0 + k, "t0": t, "dt": 20,
                                       "ax": ra[:, 0].tolist(), "ay": ra[:, 1].tolist(), "az": ra[:, 2].tolist(),
                                       "gx": rg[:, 0].tolist(), "gy": rg[:, 1].tolist(), "gz": rg[:, 2].tolist()}))
        out.append((f"har/{dev}/env", {"v": 1, "seq": seq0 + k, "t0": t, "dt": 100,
                                       "p_pa": pres[i:i + 25:5].round(1).tolist()}))
    return out


# ---------- đơn vị, đặc trưng ----------
def test_units_roundtrip():
    msg = {"t0": T0, "dt": 20, "ax": [0, 4096], "ay": [-4096, 0], "az": [0, 0], "gx": [655, 0], "gy": [0, 0], "gz": [0, 0]}
    arr = imu_packet_to_array(msg)
    assert arr[1, 0] == T0 + 20 and arr[1, 1] == 1.0 and arr[0, 2] == -1.0 and abs(arr[0, 4] - 10.0) < 1e-9
    assert to_raw_acc(np.array([1.0]))[0] == ACC_LSB_PER_G
    assert battery_pct(4.2) == 100 and battery_pct(3.0) == 0


def test_features_shape_and_tilt():
    acc, gyr, p = generate("stand", 2.5, RNG)
    f = extract_features(acc, gyr)
    assert f.shape == (len(FEATURE_NAMES_IMU),) and np.all(np.isfinite(f))
    fb = extract_features(acc, gyr, p)
    assert fb.shape == (len(FEATURE_NAMES_IMU) + len(FEATURE_NAMES_BARO),)
    tilt = f[FEATURE_NAMES_IMU.index("tilt_deg")]
    assert tilt < 15
    acc_l, gyr_l, _ = generate("lie", 2.5, RNG)
    assert extract_features(acc_l, gyr_l)[FEATURE_NAMES_IMU.index("tilt_deg")] > 60
    # leo cầu thang: áp suất giảm
    acc_u, gyr_u, p_u = generate("stairs_up", 2.5, RNG)
    slope = extract_features(acc_u, gyr_u, p_u)[len(FEATURE_NAMES_IMU)]
    assert slope < -1.0
    assert cnn_input(acc, gyr, p).shape == (125, 7) and cnn_input(acc, gyr).shape == (125, 6)


# ---------- ngưỡng té ----------
def test_fall_threshold_detects_fall_not_walk():
    t = lambda n: T0 + np.arange(n) * 20  # noqa: E731
    acc, gyr, _ = generate("fall", 6, np.random.default_rng(1))
    hits = detect_all(t(len(acc)), acc, gyr)
    assert len(hits) == 1 and hits[0]["peak_g"] > 2.5
    for act in ("walk", "run", "sit", "stairs_down"):
        acc, gyr, _ = generate(act, 20, np.random.default_rng(2))
        assert detect_all(t(len(acc)), acc, gyr) == [], act


# ---------- logic ----------
def test_smoother_majority_and_fall_passthrough():
    s = Smoother()
    assert [s.update(x) for x in ["walk", "walk", "sit", "walk", "sit", "sit"]] == ["walk", "walk", "walk", "walk", "sit", "sit"]
    assert s.update("fall") == "fall"
    assert s.update("sit") == "sit"


def test_segmenter():
    seg = Segmenter("har01")
    assert seg.update(1000, "walk", 0.9) is None
    assert seg.update(2000, "walk", 0.7) is None
    closed = seg.update(3000, "sit", 0.8)
    assert closed == {"dev": "har01", "start": 1000, "end": 3000, "label": "walk", "conf_avg": 0.8}
    assert seg.flush(5000)["label"] == "sit"
    assert seg.flush() is None


def _preds(fu, t0, labels, p_fall=0.0):
    out = []
    for i, lbl in enumerate(labels):
        out += fu.on_prediction(t0 + i * 1000, p_fall if lbl == "fall" else 0.01, lbl, t0 + i * 1000)
    return out


def test_fusion_confirmed_high():
    fu = FallFusion("har01")
    _preds(fu, T0 - 5000, ["walk"] * 5 + ["fall", "lie", "lie"], p_fall=0.9)
    assert fu.on_device_event({"id": "har01-1", "type": "suspected", "t": T0 + 500, "peak_g": 3.4}, T0 + 2500) == []
    out = fu.on_device_event({"id": "har01-2", "type": "confirmed", "t": T0 + 12500, "ref": "har01-1"}, T0 + 12500)
    assert len(out) == 1 and out[0]["severity"] == "high" and out[0]["source"] == "both"
    assert out[0]["id"] == "har01-1" and out[0]["prev_label"] == "walk" and out[0]["notify"]
    # gửi lại confirmed không tạo cảnh báo thứ hai
    assert fu.on_device_event({"id": "x", "type": "confirmed", "t": T0, "ref": "har01-1"}, T0 + 13000) == []


def test_fusion_confirmed_low_model_prob_still_alerts():
    fu = FallFusion("har01")
    _preds(fu, T0 - 3000, ["sit"] * 6)
    fu.on_device_event({"id": "a", "type": "suspected", "t": T0}, T0)
    out = fu.on_device_event({"id": "b", "type": "confirmed", "t": T0 + 12000, "ref": "a"}, T0 + 12000)
    assert out[0]["severity"] == "medium" and out[0]["source"] == "threshold"


def test_fusion_cancelled_not_notified_and_timeout():
    fu = FallFusion("har01")
    fu.on_device_event({"id": "a", "type": "suspected", "t": T0}, T0)
    out = fu.on_device_event({"id": "b", "type": "cancelled", "t": T0 + 4000, "ref": "a"}, T0 + 4000)
    assert out[0]["cancelled"] and not out[0]["notify"]
    fu.on_device_event({"id": "c", "type": "suspected", "t": T0 + 60000}, T0 + 60000)
    assert fu.tick(T0 + 70000) == []
    out = fu.tick(T0 + 76000)
    assert len(out) == 1 and out[0]["id"] == "c" and out[0]["reason"] == "timeout"


def test_fusion_model_only_requires_lying():
    fu = FallFusion("har01")
    out = _preds(fu, T0, ["walk", "fall", "lie", "lie", "lie", "lie", "lie", "lie", "lie"], p_fall=0.9)
    assert len(out) == 1 and out[0]["source"] == "model" and out[0]["severity"] == "medium"
    fu2 = FallFusion("har01")
    assert _preds(fu2, T0, ["walk", "fall", "stand", "walk", "walk", "walk", "walk", "walk"], p_fall=0.9) == []


def test_fusion_sos():
    out = FallFusion("har01").on_device_event({"id": "s", "type": "sos", "t": T0}, T0)
    assert out[0]["type"] == "sos" and out[0]["severity"] == "high"


def test_tech_monitor():
    tm = TechMonitor("har01", offline_after_ms=120_000)
    assert tm.on_status({"online": True, "battery_v": 3.9}, T0) == []
    low = tm.on_status({"online": True, "battery_v": 3.3}, T0 + 1000)
    assert low[0]["type"] == "low_battery"
    assert tm.on_status({"online": True, "battery_v": 3.3}, T0 + 2000) == []  # không lặp
    tm.on_status({"online": False}, T0 + 3000)
    assert tm.tick(T0 + 60_000) == []
    off = tm.tick(T0 + 124_000)
    assert off[0]["type"] == "offline" and tm.tick(T0 + 200_000) == []


# ---------- outbox + uplink ----------
def test_outbox_status_coalesce_and_uplink(conn):
    for i in range(3):
        store.outbox_put(conn, "status", "har01", {"dev": "har01", "t": T0 + i}, "har01")
    store.outbox_put(conn, "segments", "har01:1", {"dev": "har01", "start": 1, "end": 2, "label": "walk"}, "har01")
    store.outbox_put(conn, "event", "e1", {"id": "e1", "dev": "har01", "t": T0, "type": "fall"}, "har01")
    assert store.outbox_count_pending(conn) == 3  # status đã gộp còn 1
    pub = ConsolePublisher()
    up = Uplink(conn, pub)
    assert up.drain_once() == 3
    assert [k for k, _ in pub.sent] == ["events", "status", "segments"]
    assert pub.sent[0][1][0]["delivered_late"] is True  # T0 đã lâu
    assert store.outbox_count_pending(conn) == 0


def test_uplink_backoff_keeps_records(conn):
    def handler(req):
        return httpx.Response(503, text="down")

    pub = HttpPublisher("http://x/api", "k", client=httpx.Client(base_url="http://x/api", transport=httpx.MockTransport(handler)))
    store.outbox_put(conn, "segments", "a", {"dev": "har01"}, "har01")
    up = Uplink(conn, pub)
    assert up.step() == 2.0 and up.step() == 4.0
    assert store.outbox_count_pending(conn) == 1
    with pytest.raises(PublishError):
        pub.publish_status({})


def test_http_publisher_sends_key_and_body():
    seen = {}

    def handler(req):
        seen["key"] = req.headers["X-Device-Key"]
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    pub = HttpPublisher("http://x/api", "secret", client=httpx.Client(
        base_url="http://x/api", headers={"X-Device-Key": "secret"}, transport=httpx.MockTransport(handler)))
    pub.publish_segments([{"a": 1}])
    assert seen == {"key": "secret", "path": "/api/ingest/segments", "body": {"v": 1, "segments": [{"a": 1}]}}


# ---------- ingest ----------
def test_ingest_session_seq_and_ack(tmp_path, conn):
    ing = Ingest(tmp_path, conn)
    acc, gyr, p = generate("walk", 5, RNG)
    pk = packets(acc, gyr, p)
    ing.handle("har/har01/session", {"action": "start", "id": "s1", "subject": "S01", "activity": "walk"}, T0)
    for i, (topic, msg) in enumerate(pk):
        if i == 6:  # bỏ một gói imu -> phải đếm được 1 gói mất
            continue
        ing.handle(topic, msg, T0 + 100)
    ack = ing.handle("har/har01/event", {"id": "har01-9", "type": "marker", "t": T0}, T0)
    assert ack == [("har/har01/ack", {"v": 1, "id": "har01-9"})]
    ing.handle("har/har01/session", {"action": "stop"}, T0 + 6000)
    meta = json.loads((tmp_path / "sessions" / "s1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["lost"] == 1 and meta["packets"] == 9 and meta["end"] == T0 + 6000
    lines = (tmp_path / "sessions" / "s1" / "imu.csv").read_text().strip().splitlines()
    assert lines[0] == "t,ax,ay,az,gx,gy,gz" and len(lines) == 1 + 9 * 25
    ing.flush_counts(T0, force=True)
    assert conn.execute("SELECT SUM(lost) FROM link_counts").fetchone()[0] == 1
    ing.close()


# ---------- infer: toàn tuyến không cần broker ----------
def test_infer_pipeline_with_fall(conn):
    cfg = Config(status_every_s=5)
    inf = Infer(cfg, conn, HeuristicModel())
    rng = np.random.default_rng(3)
    parts = [generate("walk", 10, rng), generate("sit", 10, rng), generate("fall", 6, rng), generate("lie", 8, rng)]
    acc = np.concatenate([x[0] for x in parts])
    gyr = np.concatenate([x[1] for x in parts])
    pres = np.concatenate([x[2] for x in parts])
    out = []
    for topic, msg in packets(acc, gyr, pres):
        now = msg["t0"] + 520
        out += inf.handle(topic, msg, now)
        out += inf.tick(now)
    # ESP32 báo nghi té lúc va chạm (giây 21,3) rồi xác nhận sau 10 s
    t_imp = T0 + 21_300
    out += inf.handle("har/har01/event", {"id": "har01-x", "type": "suspected", "t": t_imp, "peak_g": 3.5}, t_imp + 2000)
    out += inf.handle("har/har01/event", {"id": "har01-y", "type": "confirmed", "t": t_imp + 12000, "ref": "har01-x"}, t_imp + 12000)

    preds = [p for t, p, *_ in out if t.endswith("/pred")]
    assert len(preds) >= 30
    labels = [p["label"] for p in preds]
    assert "walk" in labels and "sit" in labels and "lie" in labels
    alerts = [p for t, p, *_ in out if t.endswith("/alert")]
    fall_alerts = [a for a in alerts if a["type"] == "fall"]
    assert fall_alerts and fall_alerts[-1]["id"] == "har01-x" and fall_alerts[-1]["severity"] == "high"
    assert {r["kind"] for r in conn.execute("SELECT DISTINCT kind FROM outbox")} >= {"status", "segments", "event"}
    segs = [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM outbox WHERE kind='segments' ORDER BY created_at")]
    assert segs[0]["label"] == "walk" and all(s["end"] > s["start"] for s in segs)
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE notify = 1").fetchone()[0] >= 1
    # số liệu hệ thống tổng hợp được (latency đo theo giờ thật nên dùng ngày của T0)
    from datetime import datetime

    sm = compute_system_metrics(conn, datetime.fromtimestamp(T0 / 1000))
    assert sm == [] or sm[0]["dev"] == "har01"


# ---------- notify ----------
def test_notify_dedup_merge_cancel(conn, tmp_path):
    sent = []

    def handler(req):
        sent.append(json.loads(req.content)["text"])
        return httpx.Response(200, json={"ok": True})

    cfg = Config(telegram_bot_token="t", telegram_chat_id="1", webapp_url="https://har.example")
    n = Notifier(cfg, conn, client=httpx.Client(transport=httpx.MockTransport(handler)))

    def add(aid, t, typ="fall", notify=1, cancelled=False):
        a = {"id": aid, "dev": "har01", "t": t, "type": typ, "severity": "high", "source": "both", "prob": 0.91,
             "prev_label": "walk", "cancelled": cancelled, "notify": bool(notify), "battery_pct": 80}
        conn.execute("INSERT INTO alerts (id, dev, t, type, payload, notify, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (aid, "har01", t, typ, json.dumps(a), notify, t))

    now = store.now_ms()
    add("a1", now)
    add("a2", now + 20_000)  # cách < 60 s -> gộp
    add("a3", now + 5_000, notify=0, cancelled=True)
    add("a4", now - 3_600_000, typ="sos")  # cũ -> "gửi trễ"
    n.step(now + 30_000)
    assert len(sent) == 2
    assert any("PHÁT HIỆN TÉ" in s and "91%" in s and "Đi" in s for s in sent)
    assert any("SOS" in s and "Gửi trễ" in s for s in sent)
    n.step(now + 31_000)
    assert len(sent) == 2
    assert "/alerts" in format_message({"id": "x", "dev": "d", "t": now, "type": "fall"}, now, "https://h")
