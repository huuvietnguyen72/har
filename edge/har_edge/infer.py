"""har-infer: cửa sổ trượt 2,5 s mỗi 1 s, chạy model, làm mượt, gộp đoạn, hợp nhất cảnh báo té.

Đầu vào : har/+/imu, har/+/env, har/+/event, har/+/status (từ ESP32)
Đầu ra  : har/{dev}/pred (mỗi 1 s), har/{dev}/alert, har/{dev}/display (OLED)
          + SQLite: predictions, alerts, outbox (status 5 s, segments, events)

Chạy: python -m har_edge.infer
"""
import json
import logging
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from . import store
from .config import Config, load_config
from .features import smooth_pressure
from .logic import FallFusion, FusionParams, Segmenter, Smoother, TechMonitor
from .model import BaseModel, load_model
from .units import battery_pct, env_packet_to_array, imu_packet_to_array

log = logging.getLogger("har-infer")

PRED_EVERY_MS = 1000
GAP_MS = 1000  # khoảng trống dữ liệu lớn hơn -> bỏ bộ đệm, đóng đoạn
ONLINE_TIMEOUT_MS = 10_000


@dataclass
class DeviceState:
    dev: str
    n: int
    cfg: Config
    imu: deque = field(init=False)
    pressure: deque = field(default_factory=lambda: deque(maxlen=120))
    last_pred_t: int = 0
    last_sample_t: int = 0
    last_packet_now: int = 0
    last_status_now: int = 0
    label: str | None = None
    conf: float | None = None
    esp: dict = field(default_factory=dict)  # trạng thái ESP32 mới nhất
    temp_c: float | None = None
    rh: float | None = None
    n_pred: int = 0

    def __post_init__(self):
        self.imu = deque(maxlen=self.n + 50)
        self.smoother = Smoother(3)
        self.segmenter = Segmenter(self.dev)
        self.fusion = FallFusion(
            self.dev,
            FusionParams(p_confirm=self.cfg.fall_p_confirm, p_model_only=self.cfg.fall_p_model_only,
                         lie_after_s=self.cfg.fall_lie_after_s),
        )
        self.tech = TechMonitor(self.dev, self.cfg.low_battery_v, int(self.cfg.offline_alert_s * 1000))

    def online(self, now: int) -> bool:
        return self.esp.get("online", True) is not False and now - self.last_packet_now < ONLINE_TIMEOUT_MS


class Infer:
    def __init__(self, cfg: Config, conn, model: BaseModel):
        self.cfg = cfg
        self.conn = conn
        self.model = model
        self.devs: dict[str, DeviceState] = {}
        self.lock = threading.Lock()

    def _dev(self, dev: str) -> DeviceState:
        if dev not in self.devs:
            self.devs[dev] = DeviceState(dev, self.model.n_samples, self.cfg)
        return self.devs[dev]

    # ---------- đầu ra ----------
    def _emit_alerts(self, st: DeviceState, alerts: list[dict], out: list) -> None:
        for a in alerts:
            a["battery_pct"] = battery_pct(st.esp.get("battery_v"))
            now = store.now_ms()
            self.conn.execute(
                """INSERT OR REPLACE INTO alerts (id, dev, t, type, payload, notify, notified, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                (a["id"], a["dev"], a["t"], a["type"], json.dumps(a, ensure_ascii=False), int(a["notify"]), now),
            )
            event = {k: a.get(k) for k in ("id", "dev", "t", "type", "severity", "source", "prob", "prev_label",
                                            "battery_pct", "cancelled")}
            store.outbox_put(self.conn, "event", a["id"], event, a["dev"])
            out.append((f"har/{a['dev']}/alert", a, 1, False))
            log.warning("CẢNH BÁO %s", json.dumps(a, ensure_ascii=False))

    def _close_segment(self, st: DeviceState, seg: dict | None) -> None:
        if seg and seg["end"] > seg["start"]:
            store.outbox_put(self.conn, "segments", f"{seg['dev']}:{seg['start']}", seg, seg["dev"])

    # ---------- xử lý gói ----------
    def handle(self, topic: str, msg: dict, now: int | None = None) -> list[tuple]:
        now = now or store.now_ms()
        parts = topic.split("/")
        if len(parts) < 3:
            return []
        dev, kind = parts[1], parts[2]
        out: list[tuple] = []
        with self.lock:
            st = self._dev(dev)
            if kind == "imu":
                if msg.get("replay"):
                    return out  # dữ liệu gửi bù: har-ingest đã lưu, không suy luận thời gian thực
                arr = imu_packet_to_array(msg)
                if st.last_sample_t and arr[0, 0] - st.last_sample_t > GAP_MS:
                    st.imu.clear()
                    self._close_segment(st, st.segmenter.flush(st.last_sample_t))
                st.imu.extend(arr)
                st.last_sample_t = int(arr[-1, 0])
                st.last_packet_now = now
                st.tech.seen(now)
                if len(st.imu) >= st.n and st.last_sample_t - st.last_pred_t >= PRED_EVERY_MS:
                    self._predict(st, now, out)
            elif kind == "env":
                arr = env_packet_to_array(msg)
                st.pressure.extend(arr)
                if msg.get("temp_c") is not None:
                    st.temp_c = msg["temp_c"]
                if msg.get("rh") is not None:
                    st.rh = msg["rh"]
            elif kind == "event":
                self._emit_alerts(st, st.fusion.on_device_event(msg, now), out)
            elif kind == "status":
                st.esp.update(msg)
                if msg.get("online") is False:
                    self._close_segment(st, st.segmenter.flush(st.last_sample_t or None))
                self._emit_alerts(st, st.tech.on_status(msg, now), out)
        return out

    def _predict(self, st: DeviceState, now: int, out: list) -> None:
        win = np.asarray(list(st.imu)[-st.n:])
        t, acc, gyr = win[:, 0], win[:, 1:4], win[:, 4:7]
        pressure = None
        if self.model.use_baro:
            if len(st.pressure) >= 2:
                p = np.asarray(st.pressure)
                pressure = smooth_pressure(np.interp(t, p[:, 0], p[:, 1]))
            else:
                pressure = np.zeros(len(t))
        t0 = time.perf_counter()
        probs = self.model.predict_proba(acc, gyr, pressure)
        infer_ms = (time.perf_counter() - t0) * 1000
        raw = max(probs, key=probs.get)
        conf = float(probs[raw])
        smoothed = st.smoother.update(raw)
        p_fall = float(probs.get("fall", 0.0))
        t_end = int(t[-1])
        st.last_pred_t = t_end
        st.label, st.conf = smoothed, conf
        st.n_pred += 1

        self.conn.execute(
            "INSERT OR REPLACE INTO predictions (dev, t, label, smoothed, conf, p_fall, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (st.dev, t_end, raw, smoothed, conf, p_fall, self.model.name),
        )
        if st.n_pred % 5 == 0:
            store.add_latency(self.conn, st.dev, "infer", infer_ms, now)
            store.add_latency(self.conn, st.dev, "sample_result", store.now_ms() - t_end, now)
        top = dict(sorted(probs.items(), key=lambda kv: -kv[1])[:3])
        out.append((f"har/{st.dev}/pred", {"v": 1, "t": t_end, "label": smoothed, "raw": raw, "conf": round(conf, 3),
                                           "probs": {k: round(v, 3) for k, v in top.items()}, "model": self.model.name}, 0, False))
        self._close_segment(st, st.segmenter.update(t_end, smoothed, conf))
        self._emit_alerts(st, st.fusion.on_prediction(t_end, p_fall, smoothed, now), out)

    def tick(self, now: int | None = None) -> list[tuple]:
        now = now or store.now_ms()
        out: list[tuple] = []
        with self.lock:
            for st in self.devs.values():
                self._emit_alerts(st, st.fusion.tick(now), out)
                self._emit_alerts(st, st.tech.tick(now), out)
                online = st.online(now)
                if not online and st.segmenter.label is not None:
                    self._close_segment(st, st.segmenter.flush(st.last_sample_t))
                if now - st.last_status_now >= self.cfg.status_every_s * 1000 and (online or st.last_packet_now):
                    st.last_status_now = now
                    v = st.esp.get("battery_v")
                    status = {
                        "v": 1, "dev": st.dev, "t": now, "label": st.label if online else None,
                        "conf": round(st.conf, 3) if (online and st.conf is not None) else None,
                        "online": online, "battery_v": v, "battery_pct": battery_pct(v),
                        "temp_c": st.temp_c, "rh": st.rh, "rssi": st.esp.get("rssi"),
                        "model": self.model.name, "fw": st.esp.get("fw"),
                    }
                    store.outbox_put(self.conn, "status", st.dev, status, st.dev)
                    out.append((f"har/{st.dev}/display", {"v": 1, "label": status["label"], "conf": status["conf"],
                                                          "mode": "monitor"}, 0, True))
        return out


def main() -> None:
    from .mqtt import make_client, publish_json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    conn = store.connect(cfg.db_path)
    inf = Infer(cfg, conn, load_model(cfg.model_dir))
    client = None

    def send(items):
        for topic, payload, qos, retain in items:
            publish_json(client, topic, payload, qos=qos, retain=retain)

    topics = [("har/+/imu", 0), ("har/+/env", 0), ("har/+/event", 1), ("har/+/status", 1)]
    client = make_client(cfg, "har-infer", topics, lambda t, m: send(inf.handle(t, m)))
    client.loop_start()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.wait(0.5):
        send(inf.tick())
    with inf.lock:
        for st in inf.devs.values():
            inf._close_segment(st, st.segmenter.flush())
    client.loop_stop()


if __name__ == "__main__":
    main()
