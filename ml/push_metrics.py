"""Đẩy kết quả thí nghiệm (results/*/metrics.json) và số liệu hệ thống lên VPS.

    python push_metrics.py                                # mọi results/*/metrics.json
    python push_metrics.py results/A2/metrics.json
    python push_metrics.py --system system_metrics.json   # [{"dev","day","battery_hours",...}]

Đọc VPS_API_URL và VPS_DEVICE_KEY từ biến môi trường hoặc edge/.env.
Kết quả có "synthetic": true bị chặn, trừ khi thêm --allow-synthetic.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

import har_ml  # noqa: F401  (UTF-8 console)

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--system", type=Path, help="file JSON danh sách system_metrics")
    ap.add_argument("--allow-synthetic", action="store_true")
    a = ap.parse_args()

    load_dotenv(HERE.parent / "edge" / ".env")
    url, key = os.getenv("VPS_API_URL", "").rstrip("/"), os.getenv("VPS_DEVICE_KEY", "")
    if not url or not key:
        sys.exit("Thiếu VPS_API_URL / VPS_DEVICE_KEY")
    files = a.files or sorted((HERE / "results").glob("*/metrics.json"))
    with httpx.Client(base_url=url, headers={"X-Device-Key": key}, timeout=10) as c:
        for f in files:
            rep = json.loads(f.read_text(encoding="utf-8"))
            if (rep.get("extra") or {}).get("synthetic") and not a.allow_synthetic:
                print(f"BỎ QUA {f}: dữ liệu giả lập (thêm --allow-synthetic để thử)")
                continue
            r = c.post("/ingest/metrics", json=rep)
            print(f"{f}: HTTP {r.status_code} {r.text[:120]}")
        if a.system:
            items = json.loads(a.system.read_text(encoding="utf-8"))
            r = c.post("/ingest/system_metrics", json={"v": 1, "items": items})
            print(f"{a.system}: HTTP {r.status_code} {r.text[:120]}")


if __name__ == "__main__":
    main()
