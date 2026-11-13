"""Các đường Pi gọi (xác thực bằng X-Device-Key). Mọi đường đều idempotent:
Pi gửi lại outbox nhiều lần cũng không tạo bản ghi trùng."""
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, func, select

from ..config import get_settings
from ..db import get_session, upsert
from ..models import Device, Event, Metric, Segment, Status, StatusLog, SystemMetric, utcnow
from ..schemas import EventsIn, MetricIn, SegmentsIn, StatusIn, SystemMetricsIn
from ..security import current_device
from ..ws import manager
from .read import event_out, status_out

router = APIRouter(prefix="/api/ingest", tags=["ingest (Pi)"])


def _now_ms() -> int:
    return int(time.time() * 1000)


def _check_dev(device: Device, dev: str) -> None:
    if dev != device.dev:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"API key của {device.dev} không được ghi cho {dev}")


@router.post("/status")
def ingest_status(
    body: StatusIn,
    bg: BackgroundTasks,
    device: Device = Depends(current_device),
    session: Session = Depends(get_session),
):
    _check_dev(device, body.dev)
    now = _now_ms()
    row = body.model_dump(exclude={"v", "fw"})
    row["received_at"] = now
    upsert(session, Status, [row], ["dev"], update=[k for k in row if k != "dev"])

    if body.fw or body.model:
        device.fw = body.fw or device.fw
        device.model = body.model or device.model
        session.add(device)

    every_ms = get_settings().status_log_every_s * 1000
    last_t = session.exec(select(func.max(StatusLog.t)).where(StatusLog.dev == body.dev)).one()
    if last_t is None or body.t - last_t >= every_ms:
        session.add(
            StatusLog(
                dev=body.dev, t=body.t, online=body.online, battery_v=body.battery_v,
                battery_pct=body.battery_pct, temp_c=body.temp_c, rh=body.rh,
            )
        )
    session.commit()

    st = session.get(Status, body.dev)
    bg.add_task(manager.broadcast, "status", status_out(st, device))
    return {"ok": True, "received_at": now}


@router.post("/segments")
def ingest_segments(body: SegmentsIn, device: Device = Depends(current_device), session: Session = Depends(get_session)):
    for s in body.segments:
        _check_dev(device, s.dev)
        if s.end < s.start:
            raise HTTPException(422, "end phải ≥ start")
    n = upsert(session, Segment, [s.model_dump() for s in body.segments], ["dev", "start"])
    session.commit()
    return {"ok": True, "received": len(body.segments), "inserted": n}


@router.post("/events")
def ingest_events(
    body: EventsIn,
    bg: BackgroundTasks,
    device: Device = Depends(current_device),
    session: Session = Depends(get_session),
):
    now = _now_ms()
    rows = []
    for e in body.events:
        _check_dev(device, e.dev)
        rows.append({**e.model_dump(), "received_at": now})
    # Cùng id gửi lại: cập nhật trạng thái (ví dụ đã hủy) nhưng giữ cờ "đã xử lý" của người dùng.
    update_cols = ["t", "type", "severity", "source", "prob", "prev_label", "battery_pct", "cancelled", "delivered_late"]
    ids = [r["id"] for r in rows]
    existing = set(session.exec(select(Event.id).where(Event.id.in_(ids))).all()) if ids else set()
    upsert(session, Event, rows, ["id"], update=update_cols)
    session.commit()
    for r in rows:
        ev = session.get(Event, r["id"])
        bg.add_task(manager.broadcast, "event", {**event_out(ev), "new": r["id"] not in existing})
    return {"ok": True, "received": len(rows), "new": len([i for i in ids if i not in existing])}


@router.post("/metrics")
def ingest_metrics(body: MetricIn, device: Device = Depends(current_device), session: Session = Depends(get_session)):
    row = body.model_dump(exclude={"v"})
    row["created_at"] = utcnow()
    upsert(session, Metric, [row], ["experiment"], update=[k for k in row if k != "experiment"])
    session.commit()
    return {"ok": True, "experiment": body.experiment}


@router.post("/system_metrics")
def ingest_system_metrics(
    body: SystemMetricsIn, device: Device = Depends(current_device), session: Session = Depends(get_session)
):
    for it in body.items:
        _check_dev(device, it.dev)
    rows = [it.model_dump() for it in body.items]
    if rows:
        upsert(session, SystemMetric, rows, ["dev", "day"], update=[k for k in rows[0] if k not in ("dev", "day")])
    session.commit()
    return {"ok": True, "received": len(rows)}
