"""Bảng PostgreSQL trên VPS — giữ khớp với docs/data-schema.md.

Thời gian là epoch mili giây UTC (BigInteger).
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, Index
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Device(SQLModel, table=True):
    __tablename__ = "devices"

    dev: str = Field(primary_key=True, max_length=32)
    alias: str | None = None  # bí danh người đeo
    position: str = "hông phải"
    fw: str | None = None
    model: str | None = None  # model đang chạy trên Pi
    key_hash: str = Field(max_length=64)  # sha256 của API key, không lưu key gốc
    created_at: datetime = Field(default_factory=utcnow)


class Status(SQLModel, table=True):
    """1 dòng mỗi thiết bị, ghi đè."""

    __tablename__ = "status"

    dev: str = Field(primary_key=True, foreign_key="devices.dev", max_length=32)
    t: int = Field(sa_type=BigInteger)
    label: str | None = None
    conf: float | None = None
    online: bool = False
    battery_v: float | None = None
    battery_pct: float | None = None
    temp_c: float | None = None
    rh: float | None = None
    rssi: int | None = None
    model: str | None = None
    received_at: int = Field(sa_type=BigInteger)


class StatusLog(SQLModel, table=True):
    """Lịch sử thưa (≤ 1 dòng/phút) để vẽ đồ thị pin và đo thời lượng pin."""

    __tablename__ = "status_log"
    __table_args__ = (Index("ix_status_log_dev_t", "dev", "t"),)

    id: int | None = Field(default=None, primary_key=True)
    dev: str = Field(max_length=32)
    t: int = Field(sa_type=BigInteger)
    online: bool = False
    battery_v: float | None = None
    battery_pct: float | None = None
    temp_c: float | None = None
    rh: float | None = None


class Segment(SQLModel, table=True):
    __tablename__ = "segments"
    __table_args__ = (Index("ix_segments_dev_end", "dev", "end"),)

    dev: str = Field(primary_key=True, max_length=32)
    start: int = Field(sa_column=Column("start", BigInteger, primary_key=True))
    end: int = Field(sa_type=BigInteger)
    label: str = Field(max_length=16)
    conf_avg: float | None = None


class Event(SQLModel, table=True):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_dev_t", "dev", "t"),)

    id: str = Field(primary_key=True, max_length=64)  # do thiết bị tạo, chống trùng
    dev: str = Field(max_length=32)
    t: int = Field(sa_type=BigInteger)
    type: str = Field(max_length=16)  # fall | sos | low_battery | offline
    severity: str = Field(default="info", max_length=8)  # high | medium | info
    source: str | None = Field(default=None, max_length=16)  # threshold | model | both | device | edge
    prob: float | None = None
    prev_label: str | None = None
    battery_pct: float | None = None
    cancelled: bool = False
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    delivered_late: bool = False
    received_at: int = Field(sa_type=BigInteger)


class Metric(SQLModel, table=True):
    """Kết quả một thí nghiệm (A1, A2, B1, B2, C, D...)."""

    __tablename__ = "metrics"

    experiment: str = Field(primary_key=True, max_length=32)
    model: str
    features: str | None = None
    window_s: float | None = None
    accuracy: float | None = None
    macro_f1: float | None = None
    f1_per_class: dict[str, float] | None = Field(default=None, sa_type=JSON)
    confusion: dict[str, Any] | None = Field(default=None, sa_type=JSON)  # {"labels": [...], "matrix": [[...]]}
    n_windows: int | None = None
    n_subjects: int | None = None
    extra: dict[str, Any] | None = Field(default=None, sa_type=JSON)  # độ nhạy té, báo động giả/giờ, độ trễ suy luận...
    created_at: datetime = Field(default_factory=utcnow)


class SystemMetric(SQLModel, table=True):
    __tablename__ = "system_metrics"

    dev: str = Field(primary_key=True, max_length=32)
    day: str = Field(primary_key=True, max_length=10)  # YYYY-MM-DD theo giờ địa phương
    latency: dict[str, Any] | None = Field(default=None, sa_type=JSON)  # {"device_pi": {"median": 45, "p95": 80, "n": 1000}, ...}
    packet_loss: float | None = None  # tỉ lệ 0..1
    packets: int | None = None
    battery_hours: float | None = None
    extra: dict[str, Any] | None = Field(default=None, sa_type=JSON)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=128)
    password_hash: str
    role: str = Field(default="viewer", max_length=16)  # admin | viewer
