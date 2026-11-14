"""Thân request/response. Tên trường theo docs/data-schema.md và docs/api.md."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Label = Literal["stand", "sit", "lie", "walk", "run", "stairs_up", "stairs_down", "fall"]
LABELS: list[str] = ["stand", "sit", "lie", "walk", "run", "stairs_up", "stairs_down", "fall"]


class StatusIn(BaseModel):
    v: int = 1
    dev: str
    t: int
    label: Label | None = None
    conf: float | None = Field(default=None, ge=0, le=1)
    online: bool = True
    battery_v: float | None = None
    battery_pct: float | None = Field(default=None, ge=0, le=100)
    temp_c: float | None = None
    rh: float | None = None
    rssi: int | None = None
    model: str | None = None
    fw: str | None = None


class SegmentIn(BaseModel):
    dev: str
    start: int
    end: int
    label: Label
    conf_avg: float | None = Field(default=None, ge=0, le=1)


class SegmentsIn(BaseModel):
    v: int = 1
    segments: list[SegmentIn] = Field(max_length=1000)


class EventIn(BaseModel):
    id: str = Field(max_length=64)
    dev: str
    t: int
    type: Literal["fall", "sos", "low_battery", "offline"]
    severity: Literal["high", "medium", "info"] = "info"
    source: Literal["threshold", "model", "both", "device", "edge"] | None = None
    prob: float | None = Field(default=None, ge=0, le=1)
    prev_label: str | None = None
    battery_pct: float | None = None
    cancelled: bool = False
    delivered_late: bool = False


class EventsIn(BaseModel):
    v: int = 1
    events: list[EventIn] = Field(max_length=500)


class MetricIn(BaseModel):
    v: int = 1
    experiment: str = Field(max_length=32)
    model: str
    features: str | None = None
    window_s: float | None = None
    accuracy: float | None = None
    macro_f1: float | None = None
    f1_per_class: dict[str, float] | None = None
    confusion: dict[str, Any] | None = None
    n_windows: int | None = None
    n_subjects: int | None = None
    extra: dict[str, Any] | None = None


class SystemMetricIn(BaseModel):
    dev: str
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    latency: dict[str, Any] | None = None
    packet_loss: float | None = None
    packets: int | None = None
    battery_hours: float | None = None
    extra: dict[str, Any] | None = None


class SystemMetricsIn(BaseModel):
    v: int = 1
    items: list[SystemMetricIn] = Field(max_length=100)


class LoginIn(BaseModel):
    email: str
    password: str


class EventPatch(BaseModel):
    acknowledged: bool = True
