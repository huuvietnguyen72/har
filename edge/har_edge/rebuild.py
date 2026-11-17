"""Tạo lại dữ liệu của phiên thu từ luồng thô data/raw theo THỜI ĐIỂM ĐO.

Bản har-ingest trước 17/11/2026 gán gói vào phiên theo lúc gói tới Pi: gói tới trễ (sóng yếu ở cầu
thang, gửi bù) lọt sang phiên sau, gói tới sau lệnh dừng bị bỏ. data/raw ghi mọi mẫu theo thời điểm đo,
nên có thể cắt lại đúng khoảng [start, end] của từng phiên mà không cần thu lại.
"""
import csv
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENV_HEADER = ["t", "p_pa"]
IMU_HEADER = ["t", "ax", "ay", "az", "gx", "gy", "gz"]


def _raw_files(data_dir: Path, dev: str, kind: str, start: int, end: int):
    # file theo giờ UTC của mẫu ĐẦU gói -> gói vắt qua đầu giờ nằm ở file giờ trước: đọc từ giờ trước start
    t = datetime.fromtimestamp(start / 1000, tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    t -= timedelta(hours=1)
    last = datetime.fromtimestamp(end / 1000, tz=timezone.utc)
    while t <= last:
        p = Path(data_dir) / "raw" / dev / f"{t:%Y-%m-%d}" / f"{t:%H}_{kind}.csv"
        if p.exists():
            yield p
        t += timedelta(hours=1)


def _collect(files, start: int, end: int) -> list[list[str]]:
    rows: dict[int, list[str]] = {}
    for p in files:
        with open(p, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if row and row[0]:
                    t = int(float(row[0]))
                    if start <= t <= end:
                        rows.setdefault(t, row)
    return [rows[k] for k in sorted(rows)]


def _first_t(path: Path) -> tuple[int, int | None]:
    """(số dòng dữ liệu, t đầu tiên) của một CSV phiên."""
    if not path.exists():
        return 0, None
    with open(path, newline="", encoding="utf-8") as f:
        body = [r for r in list(csv.reader(f))[1:] if r]
    return len(body), (int(float(body[0][0])) if body else None)


def _write(path: Path, header: list[str], rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def rebuild_session(data_dir: Path, conn, sdir: Path, backup_root: Path | None = None, dry_run: bool = False) -> dict:
    """Ghi lại imu.csv, env.csv, events.csv của thư mục phiên sdir. Trả tóm tắt trước/sau."""
    sdir = Path(sdir)
    meta = json.loads((sdir / "meta.json").read_text(encoding="utf-8"))
    start, end, dev = meta.get("start"), meta.get("end"), meta.get("dev", "har01")
    res = {"id": meta.get("id", sdir.name)}
    if not start or not end:
        return {**res, "skipped": "phiên chưa kết thúc"}
    old_n, old_t0 = _first_t(sdir / "imu.csv")
    imu = _collect(_raw_files(data_dir, dev, "imu", start, end), start, end)
    env = _collect(_raw_files(data_dir, dev, "env", start, end), start, end)
    res.update(old_samples=old_n, old_offset_ms=None if old_t0 is None else old_t0 - start,
               new_samples=len(imu), new_offset_ms=(int(float(imu[0][0])) - start) if imu else None,
               env=len(env))
    if not imu:
        return {**res, "skipped": "không có dữ liệu thô trong khoảng phiên"}
    if dry_run:
        return res
    if backup_root is not None:
        shutil.copytree(sdir, Path(backup_root) / sdir.name, dirs_exist_ok=True)
    _write(sdir / "imu.csv", IMU_HEADER, imu)
    _write(sdir / "env.csv", ENV_HEADER, env)
    if conn is not None:
        ev = conn.execute("SELECT t, type, id FROM device_events WHERE dev = ? AND t BETWEEN ? AND ? ORDER BY t",
                          (dev, start, end)).fetchall()
        _write(sdir / "events.csv", ["t", "type", "id"], ev)
        res["events"] = len(ev)
    meta["samples"] = len(imu)
    meta["rebuilt_from_raw"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (sdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return res
