"""Tạo lại dữ liệu các phiên thu từ data/raw theo thời điểm đo (xem har_edge/rebuild.py).

    python rebuild_sessions.py --all --dry-run      # xem trước, không ghi gì
    python rebuild_sessions.py --all                # ghi lại mọi phiên (sao lưu vào data/sessions_backup/)
    python rebuild_sessions.py har01_S02_stairs_up_20261117-094906

Dừng har-ingest không cần thiết, nhưng KHÔNG chạy khi đang thu một phiên.
"""
import argparse
from datetime import datetime
from pathlib import Path

from har_edge import store
from har_edge.config import load_config
from har_edge.rebuild import rebuild_session


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="id phiên (tên thư mục trong data/sessions)")
    ap.add_argument("--all", action="store_true", help="mọi phiên đã kết thúc")
    ap.add_argument("--dry-run", action="store_true", help="chỉ in so sánh, không ghi")
    a = ap.parse_args()
    cfg = load_config()
    root = Path(cfg.data_dir) / "sessions"
    dirs = sorted(p for p in root.iterdir() if p.is_dir()) if a.all else [root / i for i in a.ids]
    if not dirs:
        ap.error("chỉ định id phiên hoặc --all")
    backup = None if a.dry_run else Path(cfg.data_dir) / "sessions_backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
    conn = store.connect(cfg.db_path)
    for d in dirs:
        r = rebuild_session(cfg.data_dir, conn, d, backup, a.dry_run)
        if "skipped" in r:
            print(f"{r['id']}: bỏ qua ({r['skipped']})")
            continue
        print(f"{r['id']}: mẫu {r['old_samples']} -> {r['new_samples']}, lệch đầu phiên "
              f"{r['old_offset_ms']} -> {r['new_offset_ms']} ms, áp suất {r['env']} mẫu"
              + (f", sự kiện {r['events']}" if "events" in r else ""))
    if backup:
        print("Bản cũ đã sao lưu ở", backup)


if __name__ == "__main__":
    main()
