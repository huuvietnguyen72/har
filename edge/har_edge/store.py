"""SQLite cục bộ trên Pi, dùng chung giữa các dịch vụ (chế độ WAL).

Bảng:
- outbox      : mọi bản ghi cần đẩy lên cloud (sent = 0/1)
- alerts      : cảnh báo đã hợp nhất, har-notify đọc để gửi Telegram
- device_events : sự kiện thô từ ESP32 (suspected/cancelled/confirmed/sos/marker)
- sessions    : phiên thu dữ liệu có nhãn
- predictions : dự đoán mỗi 1 s (để đối chiếu sau)
- latency     : mẫu đo độ trễ từng chặng
- link_counts : số gói nhận/mất theo phút
"""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    dev TEXT,
    priority INTEGER NOT NULL DEFAULT 5,
    payload TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    sent_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox (sent, priority, created_at);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    dev TEXT NOT NULL,
    t INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    notify INTEGER NOT NULL DEFAULT 1,
    notified INTEGER NOT NULL DEFAULT 0,
    notified_at INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alerts_pending ON alerts (notified, notify, t);

CREATE TABLE IF NOT EXISTS device_events (
    id TEXT PRIMARY KEY,
    dev TEXT NOT NULL,
    t INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    received_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    dev TEXT NOT NULL,
    subject TEXT,
    activity TEXT,
    note TEXT,
    start INTEGER NOT NULL,
    end INTEGER,
    path TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
    dev TEXT NOT NULL,
    t INTEGER NOT NULL,
    label TEXT NOT NULL,
    smoothed TEXT,
    conf REAL,
    p_fall REAL,
    model TEXT,
    PRIMARY KEY (dev, t)
);

CREATE TABLE IF NOT EXISTS latency (
    dev TEXT NOT NULL,
    t INTEGER NOT NULL,
    stage TEXT NOT NULL,
    ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_latency ON latency (stage, t);

CREATE TABLE IF NOT EXISTS link_counts (
    dev TEXT NOT NULL,
    minute INTEGER NOT NULL,
    received INTEGER NOT NULL DEFAULT 0,
    lost INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dev, minute)
);
"""

PRIORITY = {"event": 0, "status": 3, "segments": 5, "system_metrics": 7, "metrics": 8}


def now_ms() -> int:
    return int(time.time() * 1000)


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


# ---------- outbox ----------
def outbox_put(conn: sqlite3.Connection, kind: str, record_id: str, payload: dict, dev: str | None = None) -> None:
    """Thêm bản ghi vào outbox. id trùng thì ghi đè nội dung và đặt lại sent = 0.

    Riêng 'status' (ghi đè trên cloud) chỉ giữ bản mới nhất chưa gửi của mỗi thiết bị.
    """
    if kind == "status":
        conn.execute("DELETE FROM outbox WHERE kind = 'status' AND dev = ? AND sent = 0", (dev,))
    conn.execute(
        """INSERT INTO outbox (id, kind, dev, priority, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, sent = 0, attempts = 0""",
        (f"{kind}:{record_id}", kind, dev, PRIORITY.get(kind, 5), json.dumps(payload), now_ms()),
    )


def outbox_pending(conn: sqlite3.Connection, kind: str, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outbox WHERE sent = 0 AND kind = ? ORDER BY created_at LIMIT ?", (kind, limit)
    ).fetchall()


def outbox_mark_sent(conn: sqlite3.Connection, ids: list[str]) -> None:
    if ids:
        conn.executemany("UPDATE outbox SET sent = 1, sent_at = ? WHERE id = ?", [(now_ms(), i) for i in ids])


def outbox_mark_failed(conn: sqlite3.Connection, ids: list[str]) -> None:
    if ids:
        conn.executemany("UPDATE outbox SET attempts = attempts + 1 WHERE id = ?", [(i,) for i in ids])


def outbox_count_pending(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM outbox WHERE sent = 0").fetchone()[0]


def outbox_purge(conn: sqlite3.Connection, older_than_days: int = 7) -> None:
    cutoff = now_ms() - older_than_days * 86400_000
    conn.execute("DELETE FROM outbox WHERE sent = 1 AND sent_at < ?", (cutoff,))


# ---------- đo đạc ----------
def add_latency(conn: sqlite3.Connection, dev: str, stage: str, ms: float, t: int | None = None) -> None:
    conn.execute("INSERT INTO latency (dev, t, stage, ms) VALUES (?, ?, ?, ?)", (dev, t or now_ms(), stage, float(ms)))


def add_link_counts(conn: sqlite3.Connection, dev: str, minute: int, received: int, lost: int) -> None:
    conn.execute(
        """INSERT INTO link_counts (dev, minute, received, lost) VALUES (?, ?, ?, ?)
           ON CONFLICT(dev, minute) DO UPDATE SET received = received + excluded.received, lost = lost + excluded.lost""",
        (dev, minute, received, lost),
    )
