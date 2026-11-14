"""Bắt đầu/kết thúc một phiên thu dữ liệu có nhãn (chạy trên Pi hoặc laptop SSH vào Pi).

    python record.py --subject S01 --activity walk              # Enter để dừng
    python record.py --subject S01 --activity sit --duration 180
    python record.py --subject S01 --activity fall --note "nga truoc, lan 3"

har-ingest nhận lệnh qua har/{dev}/session và ghi data/sessions/{id}/.
Mỗi phiên chỉ một hoạt động; nhãn gắn theo phiên.
"""
import argparse
import sys
import time

from har_edge import LABELS
from har_edge.config import load_config
from har_edge.mqtt import make_client, publish_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="har01")
    ap.add_argument("--subject", required=True, help="mã người tham gia, ví dụ S01")
    ap.add_argument("--activity", required=True, choices=LABELS)
    ap.add_argument("--duration", type=float, help="giây; bỏ trống thì nhấn Enter để dừng")
    ap.add_argument("--note", default="")
    ap.add_argument("--countdown", type=int, default=3, help="đếm ngược trước khi bắt đầu (giây)")
    a = ap.parse_args()

    cfg = load_config()
    client = make_client(cfg, "har-record", [])
    client.loop_start()
    time.sleep(1.0)
    if not client.is_connected():
        sys.exit(f"Không kết nối được MQTT {cfg.mqtt_host}:{cfg.mqtt_port}")

    for i in range(a.countdown, 0, -1):
        print(f"Bắt đầu sau {i}…", flush=True)
        time.sleep(1)
    sid = f"{a.dev}_{a.subject}_{a.activity}_{time.strftime('%Y%m%d-%H%M%S')}"
    publish_json(client, f"har/{a.dev}/session",
                 {"action": "start", "id": sid, "subject": a.subject, "activity": a.activity, "note": a.note}, qos=1)
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "display", "mode": "record", "activity": a.activity}, qos=1)
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "beep", "ms": 150}, qos=1)
    print(f"ĐANG THU phiên {sid}", flush=True)
    try:
        if a.duration:
            end = time.time() + a.duration
            while time.time() < end:
                print(f"\r  còn {end - time.time():5.0f} s", end="", flush=True)
                time.sleep(1)
            print()
        else:
            input("Nhấn Enter để dừng… ")
    except KeyboardInterrupt:
        print()
    publish_json(client, f"har/{a.dev}/session", {"action": "stop", "id": sid}, qos=1)
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "display", "mode": "monitor"}, qos=1)
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "beep", "ms": 400}, qos=1)
    time.sleep(0.5)
    client.loop_stop()
    print(f"Đã dừng. Dữ liệu ở data/sessions/{sid}/")


if __name__ == "__main__":
    main()
