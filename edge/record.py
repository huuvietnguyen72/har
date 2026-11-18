"""Bắt đầu/kết thúc một phiên thu dữ liệu có nhãn (chạy trên Pi hoặc laptop SSH vào Pi).

    python record.py --subject S01 --activity walk              # Enter để dừng
    python record.py --subject S01 --activity sit --duration 180
    python record.py --subject S01 --activity fall --note "nga truoc, lan 3"

har-ingest nhận lệnh qua har/{dev}/session và ghi data/sessions/{id}/.
Trước khi đếm ngược, người đeo ĐỨNG THẲNG yên ~3 s để bộ đeo đo hướng đứng thẳng (calibrate_upright);
vector này lưu trên bộ đeo (bộ phát hiện té dùng) và ghi vào meta.json ("upright") để huấn luyện.
Phiên bắt đầu ở tư thế khác (nằm, ngồi): vẫn đứng thẳng lúc hiệu chỉnh rồi vào tư thế khi đếm ngược.
Mỗi phiên chỉ một hoạt động; nhãn gắn theo phiên.
"""
import argparse
import sys
import time

import numpy as np

from har_edge import LABELS
from har_edge.config import load_config
from har_edge.features import UPRIGHT
from har_edge.mqtt import make_client, publish_json

CONFIRM_ANGLE_DEG = 45  # lệch hơn mức này so với hướng mặc định thì hỏi lại người thu


def angle_deg(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    c = a @ b / (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def calibrate_upright(client, dev: str, status: dict, skip: bool, timeout_s: float = 15.0):
    """Nhờ bộ đeo đo hướng đứng thẳng của người đeo (lệnh calibrate_upright, kết quả trong status).
    Trả (vector, nguồn): nguồn là measured | nvs | default | manual | unknown."""
    time.sleep(1.5)  # chờ status retained
    before = status.get("upright")
    if skip:
        print(f"Bỏ hiệu chỉnh hướng đeo, dùng hướng trên bộ đeo: {before} ({status.get('upright_cal', 'unknown')})")
        return before, status.get("upright_cal", "unknown")

    req = f"rec-{int(time.time())}"
    print("Hiệu chỉnh hướng đeo: ĐỨNG THẲNG, tay buông, giữ yên khoảng 3 giây…", flush=True)
    publish_json(client, f"har/{dev}/cmd", {"cmd": "calibrate_upright", "id": req}, qos=1)
    end = time.time() + timeout_s
    st = None
    while time.time() < end:
        if status.get("upright_req") == req and status.get("upright_result") not in (None, "pending"):
            st = dict(status)
            break
        time.sleep(0.2)

    if st is None:
        print("  ! Bộ đeo không trả lời (firmware cũ hoặc mất kết nối) — dùng hướng mặc định.")
        return list(map(float, UPRIGHT)), "default"
    if st.get("upright_result") != "ok":
        why = {"moving": "đang cử động", "bad_gravity": "gia tốc không phải 1 g"}.get(st["upright_result"], st["upright_result"])
        print(f"  ! Không hiệu chỉnh được ({why}) — giữ hướng đang dùng: {st.get('upright')} ({st.get('upright_cal')})")
        return st.get("upright"), st.get("upright_cal", "unknown")

    up = st["upright"]
    ang = angle_deg(up, UPRIGHT)
    print(f"  Hướng đứng thẳng: {up}, lệch {ang:.0f}° so với mặc định")
    if ang > CONFIRM_ANGLE_DEG:
        ans = input(f"  Lệch hơn {CONFIRM_ANGLE_DEG}° (đeo nghiêng/ngược, hoặc người đeo chưa đứng thẳng). "
                    "Dùng hướng này? [y/N] ").strip().lower()
        if ans != "y":
            if before:
                publish_json(client, f"har/{dev}/cmd", {"cmd": "set_upright", "up": before}, qos=1)
                print(f"  Đã khôi phục hướng cũ {before}. Chạy lại khi người đeo đứng thẳng.")
            sys.exit(1)
    return up, "measured"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="har01")
    ap.add_argument("--subject", required=True, help="mã người tham gia, ví dụ S01")
    ap.add_argument("--activity", required=True, choices=LABELS)
    ap.add_argument("--duration", type=float, help="giây; bỏ trống thì nhấn Enter để dừng")
    ap.add_argument("--note", default="")
    ap.add_argument("--countdown", type=int, default=3, help="đếm ngược trước khi bắt đầu (giây)")
    ap.add_argument("--no-upright-cal", action="store_true",
                    help="bỏ bước hiệu chỉnh hướng đứng thẳng, dùng hướng đang lưu trên bộ đeo")
    a = ap.parse_args()

    cfg = load_config()
    status: dict = {}
    client = make_client(cfg, "har-record", [(f"har/{a.dev}/status", 0)],
                         on_json=lambda topic, msg: status.update(msg))
    client.loop_start()
    time.sleep(1.0)
    if not client.is_connected():
        sys.exit(f"Không kết nối được MQTT {cfg.mqtt_host}:{cfg.mqtt_port}")

    up, up_source = calibrate_upright(client, a.dev, status, skip=a.no_upright_cal)
    angle = angle_deg(up, UPRIGHT) if up is not None else None

    for i in range(a.countdown, 0, -1):
        print(f"Bắt đầu sau {i}…", flush=True)
        time.sleep(1)
    sid = f"{a.dev}_{a.subject}_{a.activity}_{time.strftime('%Y%m%d-%H%M%S')}"
    publish_json(client, f"har/{a.dev}/session",
                 {"action": "start", "id": sid, "subject": a.subject, "activity": a.activity, "note": a.note,
                  "upright": up, "upright_source": up_source,
                  "upright_angle_deg": None if angle is None else round(angle, 1)}, qos=1)
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
    # Hủy cảnh báo té còn đang chạy (phiên té, hoặc báo nhầm khi thu) TRƯỚC khi rời chế độ thu: người đeo
    # không phải nhấn nút, không sinh cảnh báo "confirmed" giả, phiên kế tiếp không bị cảnh báo cũ chặn.
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "cancel_alarm"}, qos=1)
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "display", "mode": "monitor"}, qos=1)
    publish_json(client, f"har/{a.dev}/cmd", {"cmd": "beep", "ms": 400}, qos=1)
    time.sleep(0.5)
    client.loop_stop()
    print(f"Đã dừng. Dữ liệu ở data/sessions/{sid}/")


if __name__ == "__main__":
    main()
