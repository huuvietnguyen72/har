"""har-ingest: nhận gói thô từ ESP32, đổi đơn vị, kiểm tra seq, ghi file.

- Luồng liên tục: data/raw/{dev}/{YYYY-MM-DD}/{HH}_imu.csv và _env.csv (giờ UTC)
- Phiên thu có nhãn (record.py gửi har/{dev}/session):
  data/sessions/{id}/imu.csv, env.csv, events.csv, meta.json
  Mẫu được gán vào phiên theo THỜI ĐIỂM ĐO (start <= t <= end, đồng hồ ESP32 đồng bộ với Pi qua NTP),
  không theo lúc gói tới Pi: gói tới trễ (sóng yếu, gửi bù) vẫn vào đúng phiên. Sau lệnh dừng, phiên
  chờ thêm SESSION_GRACE_MS để nhận gói tới trễ rồi mới đóng; phiên kế tiếp có thể bắt đầu ngay.
- Sự kiện ESP32: lưu SQLite rồi gửi xác nhận har/{dev}/ack để ESP32 xóa khỏi LittleFS

Chạy: python -m har_edge.ingest
"""
import csv
import json
import logging
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import store
from .config import load_config
from .logutil import setup_logging
from .units import env_packet_to_array, imu_packet_to_array

# Chờ gói tới trễ sau khi dừng phiên: ESP32 giữ 60 s dữ liệu khi mất kết nối (RING_PACKETS) và cần ~25 s để
# kết nối lại (cầu thang S02 17/11: đứt 10:14:39, nối lại 10:15:02, gửi bù sau khi phiên 15 s đã đóng).
SESSION_GRACE_MS = 90_000

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


def sort_csv(path: Path) -> int:
    """Sắp theo cột t, bỏ dòng trùng t; trả số dòng dữ liệu."""
    if not path.exists():
        return 0
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    header, body = rows[0], rows[1:]
    uniq = {}
    for r in body:
        if r and r[0]:
            uniq.setdefault(int(float(r[0])), r)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(uniq[k] for k in sorted(uniq))
    return len(uniq)


class Session:
    def __init__(self, root: Path, meta: dict):
        self.meta = meta
        self.start: int = int(meta["start"])
        self.end: int | None = None
        self.dir = root / meta["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.imu = CsvSink(self.dir / "imu.csv", IMU_HEADER)
        self.env = CsvSink(self.dir / "env.csv", ENV_HEADER)
        self.events = CsvSink(self.dir / "events.csv", ["t", "type", "id"])
        self.packets = 0
        self.lost = 0
        self._write_meta()

    def covers(self, t: float) -> bool:
        return t >= self.start and (self.end is None or t <= self.end)

    def take(self, arr):
        """Các dòng (t, ...) nằm trong khoảng thời gian của phiên."""
        if not len(arr):
            return arr
        mask = arr[:, 0] >= self.start
        if self.end is not None:
            mask &= arr[:, 0] <= self.end
        return arr[mask]

    def stop(self, end: int) -> None:
        self.end = int(end)
        self.meta["end"] = self.end
        self._write_meta()

    def _write_meta(self) -> None:
        (self.dir / "meta.json").write_text(
            json.dumps({**self.meta, "packets": self.packets, "lost": self.lost}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def finalize(self) -> None:
        """Đóng file, sắp lại theo t (gói tới trễ có thể ghi sau), ghi meta lần cuối."""
        for s in (self.imu, self.env, self.events):
            s.close()
        self.meta["samples"] = sort_csv(self.dir / "imu.csv")
        sort_csv(self.dir / "env.csv")
        self._write_meta()


class Ingest:
    def __init__(self, data_dir: Path, conn):
        self.data_dir = Path(data_dir)
        self.conn = conn
        self.raw_sinks: dict[tuple[str, str], tuple[str, CsvSink]] = {}
        self.sessions: dict[str, Session] = {}  # phiên đang thu
        self.closing: list[tuple[Session, int]] = []  # (phiên đã dừng, hạn đóng) — chờ gói tới trễ
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

    def _sessions_of(self, dev: str) -> list[Session]:
        out = [s for s, _ in self.closing if s.meta["dev"] == dev]
        if dev in self.sessions:
            out.append(self.sessions[dev])
        return out

    def tick(self, now: int) -> None:
        """Đóng các phiên đã hết thời gian chờ gói tới trễ."""
        keep = []
        for s, deadline in self.closing:
            if now >= deadline:
                s.finalize()
                log.info("Kết thúc phiên %s (%d gói, mất %d, %d mẫu)", s.meta["id"], s.packets, s.lost,
                         s.meta.get("samples", 0))
            else:
                keep.append((s, deadline))
        self.closing = keep

    # ---------- xử lý gói ----------
    def handle(self, topic: str, msg: dict, now: int | None = None) -> list[tuple[str, dict]]:
        """Trả danh sách (topic, payload) cần publish (ack sự kiện)."""
        now = now or store.now_ms()
        self.tick(now)
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
            for s in self._sessions_of(dev):
                rows = s.take(arr)
                if len(rows):
                    s.imu.write_rows(rows)
                    s.packets += 1
                    s.lost += lost
        elif kind == "env":
            arr = env_packet_to_array(msg)
            self._check_seq(dev, "env", msg.get("seq"), now)
            self.stats["env"] += 1
            if len(arr):
                self._raw_sink(dev, "env", arr[0, 0]).write_rows(arr, "{:.2f}")
                for s in self._sessions_of(dev):
                    rows = s.take(arr)
                    if len(rows):
                        s.env.write_rows(rows, "{:.2f}")
        elif kind == "event":
            eid = msg.get("id")
            if not eid:
                return []
            self.conn.execute(
                "INSERT OR IGNORE INTO device_events (id, dev, t, type, payload, received_at) VALUES (?, ?, ?, ?, ?, ?)",
                (eid, dev, int(msg.get("t", now)), msg.get("type", "?"), json.dumps(msg), now),
            )
            t_ev = msg.get("t") or now
            for s in self._sessions_of(dev):
                if s.covers(t_ev):
                    s.events.w.writerow([t_ev, msg.get("type"), eid])
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
            old.stop(now)
            self.conn.execute("UPDATE sessions SET end = ? WHERE id = ?", (now, old.meta["id"]))
            self.closing.append((old, now + SESSION_GRACE_MS))
            log.info("Dừng phiên %s (%d gói, mất %d) — chờ gói tới trễ %d s", old.meta["id"], old.packets,
                     old.lost, SESSION_GRACE_MS // 1000)
        if action == "start":
            sid = msg.get("id") or f"{dev}_{msg.get('subject', 'S00')}_{msg.get('activity', 'x')}_{now}"
            meta = {"id": sid, "dev": dev, "subject": msg.get("subject"), "activity": msg.get("activity"),
                    "note": msg.get("note"), "start": now, "end": None, "orientation": "hông phải, X chỉ xuống đất",
                    # vector đứng thẳng đo lúc bắt đầu phiên (record.py), dùng khi huấn luyện
                    "upright": msg.get("upright"), "upright_source": msg.get("upright_source"),
                    "upright_angle_deg": msg.get("upright_angle_deg")}
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
        self.tick(now + SESSION_GRACE_MS)
        for _, sink in self.raw_sinks.values():
            sink.close()


def main() -> None:
    from .mqtt import make_client, publish_json

    setup_logging()  # che token Telegram, tắt log từng request của httpx
    cfg = load_config()
    conn = store.connect(cfg.db_path)
    ing = Ingest(cfg.data_dir, conn)
    client = None

    lock = threading.Lock()  # luồng MQTT (handle) và luồng chính (tick, flush) dùng chung file phiên

    def on_json(topic: str, msg: dict) -> None:
        with lock:
            out = ing.handle(topic, msg)
        for t, payload in out:
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
        with lock:
            ing.flush_counts(store.now_ms())
            ing.tick(store.now_ms())
        if time.time() - last_log > 60:
            last_log = time.time()
            log.info("imu=%d env=%d mất=%d", ing.stats["imu"], ing.stats["env"], ing.stats["lost"])
    client.loop_stop()
    with lock:
        ing.close()


if __name__ == "__main__":
    main()
