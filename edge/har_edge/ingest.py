"""har-ingest: nhận gói thô từ ESP32, đổi đơn vị, kiểm tra seq, ghi file.

- Luồng liên tục: data/raw/{dev}/{YYYY-MM-DD}/{HH}_imu.csv và _env.csv (giờ UTC)
- Phiên thu có nhãn (record.py gửi har/{dev}/session):
  data/sessions/{id}/imu.csv, env.csv, events.csv, meta.json
- Sự kiện ESP32: lưu SQLite rồi gửi xác nhận har/{dev}/ack để ESP32 xóa khỏi LittleFS

Chạy: python -m har_edge.ingest
"""
import csv
import json
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .config import load_config
from .units import env_packet_to_array, imu_packet_to_array

log = logging.getLogger("har-ingest")

IMU_HEADER = ["t", "ax", "ay", "az", "gx", "gy", "gz"]
ENV_HEADER = ["t", "p_pa"]


class CsvSink:
    def __init__(self, path: Path, header: list[str]):
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        self.f = open(path, "a", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(header)

    def write_rows(self, rows, fmt: str = "{:.5f}") -> None:
        for r in rows:
            self.w.writerow([int(r[0])] + [fmt.format(v) for v in r[1:]])
        self.f.flush()

    def close(self) -> None:
        self.f.close()


class Session:
    def __init__(self, root: Path, meta: dict):
        self.meta = meta
        self.dir = root / meta["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.imu = CsvSink(self.dir / "imu.csv", IMU_HEADER)
        self.env = CsvSink(self.dir / "env.csv", ENV_HEADER)
        self.events = CsvSink(self.dir / "events.csv", ["t", "type", "id"])
        self.packets = 0
        self.lost = 0
        self._write_meta()

    def _write_meta(self) -> None:
        (self.dir / "meta.json").write_text(
            json.dumps({**self.meta, "packets": self.packets, "lost": self.lost}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def close(self, end: int) -> None:
        self.meta["end"] = end
        self._write_meta()
        for s in (self.imu, self.env, self.events):
            s.close()


class Ingest:
    def __init__(self, data_dir: Path, conn):
        self.data_dir = Path(data_dir)
        self.conn = conn
        self.raw_sinks: dict[tuple[str, str], tuple[str, CsvSink]] = {}
        self.sessions: dict[str, Session] = {}
        self.last_seq: dict[tuple[str, str], int] = {}
        self.counts: dict[tuple[str, int], list[int]] = {}  # (dev, minute) -> [received, lost]
        self.stats = {"imu": 0, "env": 0, "lost": 0}
        self._lat_i = 0

    # ---------- tiện ích ----------
    def _raw_sink(self, dev: str, kind: str, t_ms: float) -> CsvSink:
        dt = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
        key = f"{dt:%Y-%m-%d}/{dt:%H}"
        cur = self.raw_sinks.get((dev, kind))
        if cur is None or cur[0] != key:
            if cur:
                cur[1].close()
            path = self.data_dir / "raw" / dev / f"{dt:%Y-%m-%d}" / f"{dt:%H}_{kind}.csv"
            sink = CsvSink(path, IMU_HEADER if kind == "imu" else ENV_HEADER)
            self.raw_sinks[(dev, kind)] = (key, sink)
            return sink
        return cur[1]

    def _check_seq(self, dev: str, kind: str, seq: int | None, now: int) -> int:
        if seq is None:
            return 0
        key = (dev, kind)
        last = self.last_seq.get(key)
        self.last_seq[key] = seq
        lost = 0
        if last is not None:
            if seq > last + 1:
                lost = seq - last - 1
            elif seq <= last:  # ESP32 khởi động lại, hoặc gói lặp
                lost = 0
        minute = now // 60000
        c = self.counts.setdefault((dev, minute), [0, 0])
        c[0] += 1
        c[1] += lost
        return lost

    def flush_counts(self, now: int, force: bool = False) -> None:
        cur_minute = now // 60000
        for (dev, minute), (rcv, lost) in list(self.counts.items()):
            if force or minute < cur_minute:
                store.add_link_counts(self.conn, dev, minute, rcv, lost)
                del self.counts[(dev, minute)]

    # ---------- xử lý gói ----------
    def handle(self, topic: str, msg: dict, now: int | None = None) -> list[tuple[str, dict]]:
        """Trả danh sách (topic, payload) cần publish (ack sự kiện)."""
        now = now or store.now_ms()
        parts = topic.split("/")
        if len(parts) < 3:
            return []
        dev, kind = parts[1], parts[2]
        if kind == "imu":
            arr = imu_packet_to_array(msg)
            lost = self._check_seq(dev, "imu", msg.get("seq"), now)
            self.stats["imu"] += 1
            self.stats["lost"] += lost
            self._raw_sink(dev, "imu", arr[0, 0]).write_rows(arr)
            if not msg.get("replay"):
                self._lat_i += 1
                if self._lat_i % 10 == 0:
                    store.add_latency(self.conn, dev, "device_pi", now - arr[-1, 0], now)
            s = self.sessions.get(dev)
            if s:
                s.imu.write_rows(arr)
                s.packets += 1
                s.lost += lost
        elif kind == "env":
            arr = env_packet_to_array(msg)
            self._check_seq(dev, "env", msg.get("seq"), now)
            self.stats["env"] += 1
            if len(arr):
                self._raw_sink(dev, "env", arr[0, 0]).write_rows(arr, "{:.2f}")
                s = self.sessions.get(dev)
                if s:
                    s.env.write_rows(arr, "{:.2f}")
        elif kind == "event":
            eid = msg.get("id")
            if not eid:
                return []
            self.conn.execute(
                "INSERT OR IGNORE INTO device_events (id, dev, t, type, payload, received_at) VALUES (?, ?, ?, ?, ?, ?)",
                (eid, dev, int(msg.get("t", now)), msg.get("type", "?"), json.dumps(msg), now),
            )
            s = self.sessions.get(dev)
            if s:
                s.events.w.writerow([msg.get("t"), msg.get("type"), eid])
                s.events.f.flush()
            log.info("Sự kiện %s %s", dev, msg.get("type"))
            return [(f"har/{dev}/ack", {"v": 1, "id": eid})]
        elif kind == "session":
            self._session(dev, msg, now)
        return []

    def _session(self, dev: str, msg: dict, now: int) -> None:
        action = msg.get("action")
        old = self.sessions.pop(dev, None)
        if old:
            old.close(now)
            self.conn.execute("UPDATE sessions SET end = ? WHERE id = ?", (now, old.meta["id"]))
            log.info("Kết thúc phiên %s (%d gói, mất %d)", old.meta["id"], old.packets, old.lost)
        if action == "start":
            sid = msg.get("id") or f"{dev}_{msg.get('subject', 'S00')}_{msg.get('activity', 'x')}_{now}"
            meta = {"id": sid, "dev": dev, "subject": msg.get("subject"), "activity": msg.get("activity"),
                    "note": msg.get("note"), "start": now, "end": None, "orientation": "hông phải, Y chỉ xuống đất"}
            s = Session(self.data_dir / "sessions", meta)
            self.sessions[dev] = s
            self.conn.execute(
                "INSERT OR REPLACE INTO sessions (id, dev, subject, activity, note, start, path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, dev, meta["subject"], meta["activity"], meta["note"], now, str(s.dir)),
            )
            log.info("Bắt đầu phiên %s", sid)

    def close(self) -> None:
        now = store.now_ms()
        self.flush_counts(now, force=True)
        for dev in list(self.sessions):
            self._session(dev, {"action": "stop"}, now)
        for _, sink in self.raw_sinks.values():
            sink.close()


def main() -> None:
    from .mqtt import make_client, publish_json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    conn = store.connect(cfg.db_path)
    ing = Ingest(cfg.data_dir, conn)
    client = None

    def on_json(topic: str, msg: dict) -> None:
        for t, payload in ing.handle(topic, msg):
            publish_json(client, t, payload, qos=1)

    topics = [("har/+/imu", 0), ("har/+/env", 0), ("har/+/event", 1), ("har/+/session", 1)]
    client = make_client(cfg, "har-ingest", topics, on_json)
    client.loop_start()

    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_log = time.time()
    while not stop:
        time.sleep(1)
        ing.flush_counts(store.now_ms())
        if time.time() - last_log > 60:
            last_log = time.time()
            log.info("imu=%d env=%d mất=%d", ing.stats["imu"], ing.stats["env"], ing.stats["lost"])
    client.loop_stop()
    ing.close()


if __name__ == "__main__":
    main()
