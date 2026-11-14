"""har-uplink: xả outbox SQLite lên cloud qua Publisher.

- Thứ tự ưu tiên: sự kiện → trạng thái → đoạn hoạt động → số liệu hệ thống → metrics
- Lấy theo lô 50; thành công (2xx) mới đánh dấu sent = 1
- Lỗi mạng/5xx: thử lại sau 2, 4, 8 … tối đa 60 s
- Mỗi 10 phút tổng hợp độ trễ và tỉ lệ mất gói hôm nay -> system_metrics

Chạy: python -m har_edge.uplink
"""
import json
import logging
import signal
import threading
from datetime import datetime, timedelta

import numpy as np

from . import store
from .config import load_config
from .publisher import Publisher, PublishError, RejectedError, make_publisher

log = logging.getLogger("har-uplink")
BATCH = 50
LATE_MS = 60_000


class Uplink:
    def __init__(self, conn, publisher: Publisher):
        self.conn = conn
        self.pub = publisher
        self.backoff = 0.0

    def _rows(self, kind: str, limit: int = BATCH):
        return store.outbox_pending(self.conn, kind, limit)

    def drain_once(self) -> int:
        """Gửi một lượt; trả số bản ghi đã gửi. Ném PublishError nếu mạng lỗi."""
        sent = 0
        # 1. Sự kiện (ưu tiên cao)
        rows = self._rows("event")
        if rows:
            events = []
            for r in rows:
                ev = json.loads(r["payload"])
                ev["delivered_late"] = store.now_ms() - int(ev["t"]) > LATE_MS
                events.append(ev)
            sent += self._send(rows, lambda: self.pub.publish_events(events))
        # 2. Trạng thái: chỉ bản mới nhất mỗi thiết bị (outbox_put đã gộp)
        for r in self._rows("status", 10):
            status = json.loads(r["payload"])
            resp = self._send_one(r, lambda: self.pub.publish_status(status))
            if resp and "received_at" in resp:
                store.add_latency(self.conn, status["dev"], "pi_cloud", resp["received_at"] - status["t"])
            sent += 1 if resp is not None else 0
        # 3. Đoạn hoạt động theo lô
        rows = self._rows("segments")
        if rows:
            sent += self._send(rows, lambda: self.pub.publish_segments([json.loads(r["payload"]) for r in rows]))
        # 4. Số liệu hệ thống
        rows = self._rows("system_metrics", 20)
        if rows:
            sent += self._send(rows, lambda: self.pub.publish_system_metrics([json.loads(r["payload"]) for r in rows]))
        # 5. metrics thí nghiệm
        for r in self._rows("metrics", 10):
            report = json.loads(r["payload"])
            sent += 1 if self._send_one(r, lambda: self.pub.publish_metrics(report)) is not None else 0
        return sent

    def _send(self, rows, fn) -> int:
        ids = [r["id"] for r in rows]
        try:
            fn()
        except RejectedError as e:
            log.error("Cloud từ chối %d bản ghi, bỏ qua: %s", len(ids), e)
            self.conn.executemany("UPDATE outbox SET sent = 2 WHERE id = ?", [(i,) for i in ids])
            return 0
        except PublishError:
            store.outbox_mark_failed(self.conn, ids)
            raise
        store.outbox_mark_sent(self.conn, ids)
        return len(ids)

    def _send_one(self, row, fn):
        try:
            resp = fn()
        except RejectedError as e:
            log.error("Cloud từ chối %s: %s", row["id"], e)
            self.conn.execute("UPDATE outbox SET sent = 2 WHERE id = ?", (row["id"],))
            return None
        except PublishError:
            store.outbox_mark_failed(self.conn, [row["id"]])
            raise
        store.outbox_mark_sent(self.conn, [row["id"]])
        return resp or {}

    def step(self) -> float:
        """Một vòng: trả số giây nên chờ trước vòng sau."""
        try:
            n = self.drain_once()
            self.backoff = 0.0
            if n:
                log.info("Đã gửi %d bản ghi, còn %d", n, store.outbox_count_pending(self.conn))
            return 0.2 if n else 1.0
        except PublishError as e:
            self.backoff = min(60.0, self.backoff * 2 if self.backoff else 2.0)
            log.warning("Gửi lỗi (%s), thử lại sau %.0f s; %d bản ghi chờ", e, self.backoff,
                        store.outbox_count_pending(self.conn))
            return self.backoff


def compute_system_metrics(conn, day: datetime | None = None) -> list[dict]:
    """Tổng hợp độ trễ (trung vị, p95) và tỉ lệ mất gói của một ngày (giờ địa phương của Pi)."""
    day = (day or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    a = int(day.timestamp() * 1000)
    b = int((day + timedelta(days=1)).timestamp() * 1000)
    out = []
    devs = [r[0] for r in conn.execute("SELECT DISTINCT dev FROM latency WHERE t >= ? AND t < ?", (a, b))]
    devs += [r[0] for r in conn.execute("SELECT DISTINCT dev FROM link_counts WHERE minute >= ? AND minute < ?",
                                        (a // 60000, b // 60000)) if r[0] not in devs]
    for dev in devs:
        latency = {}
        for (stage,) in conn.execute("SELECT DISTINCT stage FROM latency WHERE dev = ? AND t >= ? AND t < ?", (dev, a, b)):
            ms = np.array([r[0] for r in conn.execute(
                "SELECT ms FROM latency WHERE dev = ? AND stage = ? AND t >= ? AND t < ?", (dev, stage, a, b))])
            if len(ms):
                latency[stage] = {"median": round(float(np.median(ms)), 1), "p95": round(float(np.percentile(ms, 95)), 1),
                                  "n": int(len(ms))}
        rcv, lost = conn.execute(
            "SELECT COALESCE(SUM(received), 0), COALESCE(SUM(lost), 0) FROM link_counts WHERE dev = ? AND minute >= ? AND minute < ?",
            (dev, a // 60000, b // 60000)).fetchone()
        total = rcv + lost
        out.append({"dev": dev, "day": day.strftime("%Y-%m-%d"), "latency": latency,
                    "packet_loss": round(lost / total, 5) if total else None, "packets": int(rcv)})
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    conn = store.connect(cfg.db_path)
    up = Uplink(conn, make_publisher(cfg))
    log.info("Uplink chạy với backend=%s", cfg.cloud_backend)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    last_sys = 0.0
    import time

    while not stop.is_set():
        if time.time() - last_sys > 600:
            last_sys = time.time()
            for item in compute_system_metrics(conn):
                store.outbox_put(conn, "system_metrics", f"{item['dev']}:{item['day']}", item, item["dev"])
            store.outbox_purge(conn)
        stop.wait(up.step())
    up.pub.close()


if __name__ == "__main__":
    main()
