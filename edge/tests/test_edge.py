import json

import httpx
import numpy as np
import pytest

from har_edge import store
from har_edge.config import Config
from har_edge.fall_threshold import detect_all
from har_edge.features import (FEATURE_NAMES_BARO, FEATURE_NAMES_IMU, UPRIGHT, cnn_input, extract_features,
                               upright_vec)
from har_edge.infer import Infer
from har_edge.ingest import SESSION_GRACE_MS, Ingest
from har_edge.rebuild import rebuild_session
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
def test_tilt_uses_calibrated_upright():
    """Hộp cài nghiêng 40°: theo hướng mặc định thì đứng trông như ngồi; theo hướng đã hiệu chỉnh thì đứng."""
    acc, gyr, _ = generate("stand", 2.5, RNG)
    r = np.radians(40)
    rot = np.array([[np.cos(r), 0, -np.sin(r)], [0, 1, 0], [np.sin(r), 0, np.cos(r)]])
    acc_t, gyr_t = acc @ rot.T, gyr @ rot.T
    up = acc_t.mean(axis=0)
    i = FEATURE_NAMES_IMU.index("tilt_deg")
    assert extract_features(acc_t, gyr_t)[i] > 30
    assert extract_features(acc_t, gyr_t, up=up)[i] < 8
    m = HeuristicModel()
    p_default = m.predict_proba(acc_t, gyr_t, None)
    p_cal = m.predict_proba(acc_t, gyr_t, None, up=list(up))
    assert max(p_default, key=p_default.get) == "sit"
    assert max(p_cal, key=p_cal.get) == "stand"
    assert upright_vec(None) is UPRIGHT and upright_vec([0, 0, 0]) is UPRIGHT and upright_vec("x") is UPRIGHT
    assert np.allclose(upright_vec([0, 0, 2]), [0, 0, 1])


def test_fall_threshold_detects_fall_not_walk():
    t = lambda n: T0 + np.arange(n) * 20  # noqa: E731
    acc, gyr, _ = generate("fall", 6, np.random.default_rng(1))
    hits = detect_all(t(len(acc)), acc, gyr)
    assert len(hits) == 1 and hits[0]["peak_g"] > 2.5
    for act in ("walk", "sit", "stairs_down"):
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


def _model_fall(fu, t0=T0, p_fall=0.9, lead=("walk",)):
    """Chuỗi dự đoán: đang đi -> té -> nằm 7 s. Trả cảnh báo phát ra ngay (phải rỗng: Pi chờ bộ đeo)."""
    return _preds(fu, t0, [*lead, "fall", "lie", "lie", "lie", "lie", "lie", "lie", "lie"], p_fall=p_fall)


def test_fusion_model_only_asks_device_to_alarm():
    fu = FallFusion("har01")
    assert _model_fall(fu) == []  # không báo thẳng nữa
    assert fu.pop_commands() == [{"cmd": "test_alarm"}] and fu.pop_commands() == []
    fu2 = FallFusion("har01")  # té rồi đứng dậy đi tiếp: không nhờ bộ đeo
    assert _preds(fu2, T0, ["walk", "fall", "stand", "walk", "walk", "walk", "walk", "walk"], p_fall=0.9) == []
    assert fu2.pop_commands() == []


def test_fusion_model_alarm_confirmed_by_wearer_silence():
    fu = FallFusion("har01")
    _model_fall(fu, p_fall=0.8)
    t_req = T0 + 8000
    # bộ đeo bật cảnh báo theo lệnh (peak_g 0), người đeo không hủy -> confirmed sau 10 s
    assert fu.on_device_event({"id": "har01-a", "type": "suspected", "t": t_req + 300, "peak_g": 0.0}, t_req + 400) == []
    out = fu.on_device_event({"id": "har01-b", "type": "confirmed", "t": t_req + 10_400, "ref": "har01-a", "peak_g": 0.0}, t_req + 10_500)
    assert len(out) == 1 and out[0]["source"] == "model" and out[0]["severity"] == "high" and out[0]["notify"]
    assert out[0]["id"] == f"har01-m{T0 + 1000}" and out[0]["t"] == T0 + 1000 and out[0]["prob"] == 0.8  # giờ té, không phải giờ bật còi
    assert fu.tick(t_req + 60_000) == []  # không báo thêm lần nữa khi hết thời gian chờ


def test_fusion_model_alarm_cancelled_by_wearer():
    fu = FallFusion("har01")
    _model_fall(fu)
    t_req = T0 + 8000
    fu.on_device_event({"id": "har01-a", "type": "suspected", "t": t_req + 300, "peak_g": 0.0}, t_req + 400)
    out = fu.on_device_event({"id": "har01-c", "type": "cancelled", "t": t_req + 4000, "ref": "har01-a"}, t_req + 4100)
    assert len(out) == 1 and out[0]["cancelled"] and not out[0]["notify"] and out[0]["source"] == "model"
    assert fu.tick(t_req + 60_000) == []


def test_fusion_model_alarm_device_no_response_falls_back():
    fu = FallFusion("har01")
    _model_fall(fu)
    t_req = T0 + 8000
    assert fu.tick(t_req + 10_000) == []  # còn chờ bộ đeo
    out = fu.tick(t_req + 16_000)  # > 15 s không có "suspected": báo thẳng
    assert len(out) == 1 and out[0]["source"] == "model" and out[0]["severity"] == "medium" and out[0]["notify"]
    assert out[0]["reason"] == "device_no_response" and out[0]["t"] == T0 + 1000
    assert fu.tick(t_req + 30_000) == []


def test_fusion_model_and_real_impact_same_fall():
    """Ngưỡng trên bộ đeo cũng thấy va chạm thật ngay sau lệnh: xử lý như incident ngưỡng, không báo trùng."""
    fu = FallFusion("har01")
    _model_fall(fu)
    t_req = T0 + 8000
    fu.on_device_event({"id": "har01-x", "type": "suspected", "t": t_req + 200, "peak_g": 3.4}, t_req + 300)
    out = fu.on_device_event({"id": "har01-y", "type": "confirmed", "t": t_req + 10_300, "ref": "har01-x", "peak_g": 3.4}, t_req + 10_400)
    out += fu.tick(t_req + 60_000)
    assert [a["id"] for a in out] == ["har01-x"]


def test_fusion_model_only_threshold_and_lying_gate():
    # P(té) 0,55: đủ ngưỡng mặc định 0,5 (S01 thật cho 0,50–0,70)
    fu = FallFusion("har01")
    _preds(fu, T0, ["walk", "walk", "fall", "lie", "lie", "lie", "lie", "lie", "lie", "lie"], p_fall=0.55)
    assert fu.pop_commands() == [{"cmd": "test_alarm"}]
    # đang nằm rồi trở mình (giống SisFall D14): không nhờ bộ đeo, không báo
    fu2 = FallFusion("har01")
    assert _preds(fu2, T0, ["lie", "lie", "lie", "fall", "lie", "lie", "lie", "lie", "lie", "lie", "lie"], p_fall=0.9) == []
    assert fu2.pop_commands() == [] and fu2.tick(T0 + 60_000) == []


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


def _imu_rows(path):
    lines = path.read_text().strip().splitlines()[1:]
    return [int(l.split(",")[0]) for l in lines]


def test_ingest_session_by_sample_time(tmp_path, conn):
    """Gói tới sớm/trễ vẫn vào đúng phiên theo thời điểm đo; phiên kế tiếp không nhận gói trễ của phiên trước."""
    ing = Ingest(tmp_path, conn)
    acc, gyr, p = generate("walk", 4, RNG)
    pk = [x for x in packets(acc, gyr, p) if x[0].endswith("/imu")]  # gói i: t0 = T0 + 500 i
    ing.handle("har/har01/session", {"action": "start", "id": "a", "subject": "S01", "activity": "stairs_down"}, T0 + 250)
    for k in range(3):                                     # gói 0 bắt đầu trước start 250 ms
        ing.handle(*pk[k], T0 + 600 + k * 500)
    ing.handle("har/har01/event", {"id": "e1", "type": "marker", "t": T0 + 900}, T0 + 1000)
    ing.handle("har/har01/session", {"action": "stop"}, T0 + 2000)
    ing.handle("har/har01/session", {"action": "start", "id": "b", "subject": "S01", "activity": "stairs_up"}, T0 + 2100)
    ing.handle(*pk[3], T0 + 5000)                          # tới trễ 3 s, đo trong phiên a
    ing.handle(*pk[4], T0 + 5100)                          # 2000..2480: mẫu 2000 thuộc a, từ 2100 thuộc b
    ing.handle("har/har01/event", {"id": "e2", "type": "marker", "t": T0 + 1500}, T0 + 5200)  # sự kiện trễ của a
    ing.tick(T0 + 2000 + SESSION_GRACE_MS)
    a = tmp_path / "sessions" / "a"
    t_a = _imu_rows(a / "imu.csv")
    assert t_a[0] == T0 + 260 and t_a[-1] == T0 + 2000 and t_a == sorted(t_a)
    assert len(t_a) == 12 + 25 + 25 + 25 + 1
    meta = json.loads((a / "meta.json").read_text(encoding="utf-8"))
    assert meta["samples"] == len(t_a) and meta["end"] == T0 + 2000
    assert [l.split(",")[2] for l in (a / "events.csv").read_text().strip().splitlines()[1:]] == ["e1", "e2"]
    ing.handle("har/har01/session", {"action": "stop"}, T0 + 3000)
    ing.close()
    t_b = _imu_rows(tmp_path / "sessions" / "b" / "imu.csv")
    assert t_b[0] == T0 + 2100 and t_b[-1] == T0 + 2480 and len(t_b) == 20


def test_rebuild_session_from_raw(tmp_path, conn):
    """Phiên ghi theo lúc gói tới (bản cũ) được cắt lại đúng khoảng [start, end] từ data/raw."""
    ing = Ingest(tmp_path, conn)
    acc, gyr, p = generate("walk", 6, RNG)
    for topic, msg in packets(acc, gyr, p):
        ing.handle(topic, msg, msg["t0"] + 520)            # chỉ ghi luồng thô, không có phiên
    ing.close()
    sdir = tmp_path / "sessions" / "old"
    sdir.mkdir(parents=True)
    (sdir / "meta.json").write_text(json.dumps({"id": "old", "dev": "har01", "start": T0 + 1000, "end": T0 + 4000}))
    (sdir / "imu.csv").write_text("t,ax,ay,az,gx,gy,gz\n" + "".join(f"{T0 + 500 + i * 20},0,0,0,0,0,0\n" for i in range(10)))
    dry = rebuild_session(tmp_path, conn, sdir, dry_run=True)
    assert dry["old_samples"] == 10 and dry["old_offset_ms"] == -500 and dry["new_samples"] == 151
    r = rebuild_session(tmp_path, conn, sdir, backup_root=tmp_path / "bk")
    t = _imu_rows(sdir / "imu.csv")
    assert t[0] == T0 + 1000 and t[-1] == T0 + 4000 and len(t) == 151 and r["new_offset_ms"] == 0
    assert (tmp_path / "bk" / "old" / "imu.csv").exists()
    assert json.loads((sdir / "meta.json").read_text())["samples"] == 151


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


def test_stairs_gate_and_altitude():
    from har_edge.logic import altitude_change_m, stairs_gate

    probs = {"stand": 0.2, "stairs_up": 0.6, "walk": 0.1, "fall": 0.1}
    gated = stairs_gate(probs, 0.05, 0.3)
    assert gated["stairs_up"] == 0 and gated["stand"] == 0.2 and gated["fall"] == 0.1  # không chia lại tỉ lệ
    assert max(gated, key=gated.get) == "stand"
    assert stairs_gate(probs, 1.2, 0.3) == probs  # leo thật: giữ
    assert stairs_gate(probs, None, 0.3) == probs  # chưa đủ 10 s áp suất
    assert stairs_gate(probs, 0.0, 0) == probs  # tắt
    assert stairs_gate({"stand": 0.7, "stairs_up": 0.3}, 0.0, 0.3) == {"stand": 0.7, "stairs_up": 0.3}
    t = np.arange(0, 12_000, 100.0)
    p = 101_300 - 1.2 * t / 1000 + RNG.normal(0, 0.3, len(t))  # lên ~0,1 m/s
    alt = altitude_change_m(np.column_stack([t, p]), t[-1])
    assert 0.8 < alt < 1.2
    assert altitude_change_m(np.column_stack([t[-30:], p[-30:]]), t[-1]) is None  # mới có 3 s


def test_align_to_upright_makes_axis_features_wear_invariant():
    from har_edge.features import FEATURE_NAMES_IMU, rotation_to

    n = 125
    acc = np.tile([-1.0, 0.0, 0.0], (n, 1)) + RNG.normal(0, 0.01, (n, 3))
    gyr = RNG.normal(0, 1, (n, 3))
    up = np.array([-0.9, -0.08, -0.43])
    R = rotation_to([-1, 0, 0], up)  # cùng tư thế, hộp đeo nghiêng 26°
    f0 = extract_features(acc, gyr, up=[-1, 0, 0], align=True)
    f1 = extract_features(acc @ R.T, gyr @ R.T, up=up, align=True)
    raw = extract_features(acc @ R.T, gyr @ R.T, up=up)
    i = FEATURE_NAMES_IMU.index("ax_mean")
    assert abs(f1[i] - f0[i]) < 1e-3 and abs(raw[i] - f0[i]) > 0.05
    assert np.allclose(f0, f1, atol=1e-3)


def test_yaw_invariant_features_ignore_rotation_about_vertical():
    from har_edge.features import FEATURE_NAMES_YAW, feature_names, rotation_to

    n = 125
    t = np.arange(n) / 50
    # đi bộ: dao động thẳng đứng 2 Hz + lắc ngang theo một hướng (trước/sau)
    acc = np.column_stack([-1 - 0.3 * np.sin(2 * np.pi * 2 * t), 0.15 * np.sin(2 * np.pi * 1 * t), 0.05 * np.cos(2 * np.pi * 1 * t)])
    gyr = np.column_stack([10 * np.sin(2 * np.pi * t), 30 * np.sin(2 * np.pi * 2 * t), 5 * np.cos(2 * np.pi * t)])
    p = 101_300 + RNG.normal(0, 0.2, n)
    yaw = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)  # quay 90° quanh trục đứng X (đeo giữa bụng thay vì hông)
    tilt = rotation_to([-1, 0, 0], [-0.86, -0.48, -0.18])  # rồi nghiêng hộp ~30°
    up = tilt @ np.array([-1.0, 0, 0])
    f0 = extract_features(acc, gyr, p, up=[-1, 0, 0], yaw_invariant=True)
    f1 = extract_features(acc @ (tilt @ yaw).T, gyr @ (tilt @ yaw).T, p, up=up, yaw_invariant=True)
    assert len(f0) == len(feature_names(True, True)) == len(FEATURE_NAMES_YAW) + 3
    assert np.allclose(f0, f1, atol=1e-3)
    # bộ đặc trưng theo trục (v2) thì đổi khi quay quanh trục đứng
    a0 = extract_features(acc, gyr, p, up=[-1, 0, 0], align=True)
    a1 = extract_features(acc @ (tilt @ yaw).T, gyr @ (tilt @ yaw).T, p, up=up, align=True)
    assert not np.allclose(a0, a1, atol=1e-3)


def test_status_sent_right_after_activity_changes(conn):
    """Hoạt động đổi -> trạng thái (cloud + OLED) phát ở vòng tick kế tiếp, không chờ chu kỳ 5 s."""
    inf = Infer(Config(status_every_s=5), conn, HeuristicModel())
    rng = np.random.default_rng(5)
    parts = [generate("walk", 12, rng), generate("sit", 12, rng)]
    acc = np.concatenate([x[0] for x in parts])
    gyr = np.concatenate([x[1] for x in parts])
    pres = np.concatenate([x[2] for x in parts])
    log = []  # (now, topic, payload)
    for topic, msg in packets(acc, gyr, pres):
        now = msg["t0"] + 520
        log += [(now, t, p) for t, p, *_ in inf.handle(topic, msg, now)]
        log += [(now, t, p) for t, p, *_ in inf.tick(now)]
    changes = [(now, p["label"]) for i, (now, t, p) in enumerate(log) if t.endswith("/pred")
               and p["label"] != next((q["label"] for _, tt, q in reversed(log[:i]) if tt.endswith("/pred")), None)]
    assert [lbl for _, lbl in changes][:2] == ["walk", "sit"]
    for t_change, lbl in changes:
        shown = [now for now, t, p in log if t.endswith("/display") and p["label"] == lbl and now >= t_change]
        assert shown and shown[0] - t_change <= 1000, (lbl, shown[:1], t_change)
