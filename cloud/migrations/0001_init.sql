-- Cơ sở dữ liệu D1 (SQLite) của HAR cloud — cùng bảng và cột với backend/api/app/models.py.
-- Thời gian: epoch mili giây UTC (INTEGER). Trường JSON lưu dạng TEXT. Ngày giờ ISO cho created_at, acknowledged_at.

CREATE TABLE devices (
    dev TEXT PRIMARY KEY,
    alias TEXT,
    position TEXT NOT NULL DEFAULT 'hông phải',
    fw TEXT,
    model TEXT,
    key_hash TEXT NOT NULL,           -- sha256 hex của API key, không lưu key gốc
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE status (                 -- 1 dòng mỗi thiết bị, ghi đè
    dev TEXT PRIMARY KEY,
    t INTEGER NOT NULL,
    label TEXT,
    conf REAL,
    online INTEGER NOT NULL DEFAULT 0,
    battery_v REAL,
    battery_pct REAL,
    temp_c REAL,
    rh REAL,
    rssi INTEGER,
    model TEXT,
    received_at INTEGER NOT NULL
);

CREATE TABLE status_log (             -- lịch sử thưa (≤ 1 dòng/phút) để vẽ đồ thị pin
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dev TEXT NOT NULL,
    t INTEGER NOT NULL,
    online INTEGER NOT NULL DEFAULT 0,
    battery_v REAL,
    battery_pct REAL,
    temp_c REAL,
    rh REAL
);
CREATE INDEX ix_status_log_dev_t ON status_log (dev, t);

CREATE TABLE segments (
    dev TEXT NOT NULL,
    start INTEGER NOT NULL,
    "end" INTEGER NOT NULL,
    label TEXT NOT NULL,
    conf_avg REAL,
    PRIMARY KEY (dev, start)
);
CREATE INDEX ix_segments_dev_end ON segments (dev, "end");

CREATE TABLE events (
    id TEXT PRIMARY KEY,              -- do thiết bị tạo, chống trùng
    dev TEXT NOT NULL,
    t INTEGER NOT NULL,
    type TEXT NOT NULL,               -- fall | sos | low_battery | offline
    severity TEXT NOT NULL DEFAULT 'info',
    source TEXT,
    prob REAL,
    prev_label TEXT,
    battery_pct REAL,
    cancelled INTEGER NOT NULL DEFAULT 0,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    delivered_late INTEGER NOT NULL DEFAULT 0,
    received_at INTEGER NOT NULL
);
CREATE INDEX ix_events_dev_t ON events (dev, t);

CREATE TABLE metrics (                -- kết quả một thí nghiệm (A1, A2, B1, B2, C, D...)
    experiment TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    features TEXT,
    window_s REAL,
    accuracy REAL,
    macro_f1 REAL,
    f1_per_class TEXT,                -- JSON
    confusion TEXT,                   -- JSON {"labels": [...], "matrix": [[...]]}
    n_windows INTEGER,
    n_subjects INTEGER,
    extra TEXT,                       -- JSON
    created_at TEXT NOT NULL
);

CREATE TABLE system_metrics (
    dev TEXT NOT NULL,
    day TEXT NOT NULL,                -- YYYY-MM-DD theo giờ địa phương
    latency TEXT,                     -- JSON {"device_pi": {"median": 45, "p95": 80, "n": 1000}, ...}
    packet_loss REAL,
    packets INTEGER,
    battery_hours REAL,
    extra TEXT,                       -- JSON
    PRIMARY KEY (dev, day)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,      -- pbkdf2_sha256$<vòng lặp>$<salt b64>$<hash b64>
    role TEXT NOT NULL DEFAULT 'viewer'
);
