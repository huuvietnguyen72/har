"""Các đường web app gọi (xác thực bằng JWT)."""
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, and_, select

from ..config import get_settings
from ..db import get_session
from ..models import Device, Event, Metric, Segment, Status, StatusLog, SystemMetric, User, utcnow
from ..schemas import LABELS, EventPatch
from ..security import current_user

router = APIRouter(prefix="/api", tags=["web app"])

MAX_RANGE_MS = 8 * 24 * 3600 * 1000


def _now_ms() -> int:
    return int(time.time() * 1000)


def status_out(st: Status, device: Device | None) -> dict:
    stale = _now_ms() - st.received_at > get_settings().status_stale_s * 1000
    d = st.model_dump()
    d["online"] = bool(st.online and not stale)
    d["alias"] = device.alias if device else None
    d["fw"] = device.fw if device else None
    return d


def event_out(ev: Event) -> dict:
    d = ev.model_dump()
    if ev.acknowledged_at:
        d["acknowledged_at"] = ev.acknowledged_at.isoformat()
    return d


def _range(frm: int | None, to: int | None, default_ms: int) -> tuple[int, int]:
    to = to or _now_ms()
    frm = frm if frm is not None else to - default_ms
    if to < frm or to - frm > MAX_RANGE_MS:
        raise HTTPException(422, "Khoảng thời gian không hợp lệ (tối đa 8 ngày)")
    return frm, to


@router.get("/devices")
def list_devices(_: User = Depends(current_user), session: Session = Depends(get_session)):
    return [d.model_dump(exclude={"key_hash"}) for d in session.exec(select(Device)).all()]


@router.get("/status")
def get_status(_: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Status, Device).join(Device, Device.dev == Status.dev, isouter=True)).all()
    return [status_out(st, dev) for st, dev in rows]


@router.get("/status/history")
def status_history(
    dev: str,
    frm: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    frm, to = _range(frm, to, 24 * 3600 * 1000)
    q = select(StatusLog).where(StatusLog.dev == dev, StatusLog.t >= frm, StatusLog.t < to).order_by(StatusLog.t)
    return [r.model_dump(exclude={"id"}) for r in session.exec(q).all()]


def _segments(session: Session, dev: str, frm: int, to: int) -> list[Segment]:
    q = (
        select(Segment)
        .where(Segment.dev == dev, and_(Segment.end > frm, Segment.start < to))
        .order_by(Segment.start)
    )
    return list(session.exec(q).all())


@router.get("/segments")
def get_segments(
    dev: str,
    frm: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    frm, to = _range(frm, to, 3600 * 1000)
    return [s.model_dump() for s in _segments(session, dev, frm, to)]


def _day_bounds(day: date) -> tuple[int, int]:
    tz = ZoneInfo(get_settings().tz_name)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def summarize_day(session: Session, dev: str, day: date) -> dict:
    """Tổng hợp theo ngày, tính từ segments + events (chính là bảng daily_summary dạng 'view')."""
    a, b = _day_bounds(day)
    seconds = {lbl: 0.0 for lbl in LABELS}
    online = 0.0
    for s in _segments(session, dev, a, b):
        dur = (min(s.end, b) - max(s.start, a)) / 1000
        if dur > 0:
            seconds[s.label] = seconds.get(s.label, 0.0) + dur
            online += dur
    events = session.exec(select(Event).where(Event.dev == dev, Event.t >= a, Event.t < b)).all()
    alerts = [e for e in events if e.type in ("fall", "sos") and not e.cancelled]
    return {
        "dev": dev,
        "day": day.isoformat(),
        "seconds": {k: round(v, 1) for k, v in seconds.items()},
        "online_s": round(online, 1),
        "n_alerts": len(alerts),
        "n_cancelled": len([e for e in events if e.cancelled]),
    }


@router.get("/summary")
def get_summary(
    dev: str,
    day: date | None = None,
    days: int = Query(default=1, ge=1, le=31),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    """`day` là ngày cuối; `days=7` trả 7 ngày để so sánh (cũ → mới)."""
    day = day or datetime.now(ZoneInfo(get_settings().tz_name)).date()
    return [summarize_day(session, dev, day - timedelta(days=i)) for i in reversed(range(days))]


@router.get("/events")
def get_events(
    dev: str | None = None,
    frm: int | None = Query(default=None, alias="from"),
    to: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    _: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    q = select(Event)
    if dev:
        q = q.where(Event.dev == dev)
    if frm is not None:
        q = q.where(Event.t >= frm)
    if to is not None:
        q = q.where(Event.t < to)
    q = q.order_by(Event.t.desc()).limit(limit)
    return [event_out(e) for e in session.exec(q).all()]


@router.patch("/events/{event_id}")
def patch_event(
    event_id: str,
    body: EventPatch,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    ev = session.get(Event, event_id)
    if ev is None:
        raise HTTPException(404, "Không có sự kiện này")
    ev.acknowledged = body.acknowledged
    ev.acknowledged_at = utcnow() if body.acknowledged else None
    ev.acknowledged_by = user.email if body.acknowledged else None
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return event_out(ev)


@router.get("/metrics")
def get_metrics(_: User = Depends(current_user), session: Session = Depends(get_session)):
    experiments = session.exec(select(Metric).order_by(Metric.experiment)).all()
    system = session.exec(select(SystemMetric).order_by(SystemMetric.day.desc()).limit(60)).all()
    devices = session.exec(select(Device)).all()
    return {
        "experiments": [m.model_dump() for m in experiments],
        "system": [s.model_dump() for s in system],
        "running_models": {d.dev: d.model for d in devices},
    }
