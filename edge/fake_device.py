"""Giả lập ESP32: gửi IMU 50 Hz, áp suất 10 Hz, trạng thái, sự kiện té qua MQTT.

Dùng để thử toàn tuyến (ingest → infer → uplink → cloud → web app, notify → Telegram)
khi chưa có phần cứng. Tín hiệu là giả lập (har_edge.synth).

    python fake_device.py                                   # kịch bản mặc định, lặp mãi
    python fake_device.py --script "stand:10,walk:20,sit:15,fall:8,lie:10"
    python fake_device.py --script "walk:5,fall:8" --cancel  # nhấn "hủy" sau 3 s
    python fake_device.py --sos-after 20
"""
import argparse
import itertools
import time

import numpy as np

from har_edge.config import load_config
from har_edge.fall_threshold import FallThreshold
from har_edge.mqtt import make_client, publish_json
from har_edge.synth import generate
from har_edge.units import to_raw_acc, to_raw_gyro

DEFAULT = "stand:15,walk:30,sit:20,stairs_up:15,walk:10,stairs_down:15,run:15,lie:20,stand:5,fall:8,lie:10"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", default="har01")
    ap.add_argument("--script", default=DEFAULT, help="hoạt động:giây, cách nhau bởi dấu phẩy")
    ap.add_argument("--once", action="store_true", help="chạy kịch bản một lần rồi thoát")
    ap.add_argument("--cancel", action="store_true", help="giả lập người đeo nhấn hủy sau 3 s")
    ap.add_argument("--sos-after", type=float, help="gửi SOS sau N giây")
    ap.add_argument("--speed", type=float, default=1.0, help="tốc độ phát (2 = nhanh gấp đôi)")
    a = ap.parse_args()

    cfg = load_config()
    client = make_client(cfg, f"fake-{a.dev}", [])
    client.will_set(f"har/{a.dev}/status", '{"v":1,"online":false}', qos=1, retain=True)
    client.loop_start()
    time.sleep(1)

    rng = np.random.default_rng()
    det = FallThreshold()
    seq_imu = seq_env = 0
    battery = 4.15
    start = time.time()
    pending: dict | None = None
    sos_sent = False
    steps = [(s.split(":")[0], float(s.split(":")[1])) for s in a.script.split(",")]
    plan = steps if a.once else itertools.cycle(steps)
    t_ms = int(time.time() * 1000)
    last_status = 0.0

    for activity, dur in plan:
        print(f"→ {activity} {dur:.0f} s", flush=True)
        acc, gyr, pres = generate(activity, dur, rng)
        for i0 in range(0, len(acc) - 24, 25):
            sl = slice(i0, i0 + 25)
            ra, rg = to_raw_acc(acc[sl]), to_raw_gyro(gyr[sl])
            publish_json(client, f"har/{a.dev}/imu", {
                "v": 1, "seq": seq_imu, "t0": t_ms, "dt": 20, "replay": False,
                "ax": ra[:, 0].tolist(), "ay": ra[:, 1].tolist(), "az": ra[:, 2].tolist(),
                "gx": rg[:, 0].tolist(), "gy": rg[:, 1].tolist(), "gz": rg[:, 2].tolist()})
            publish_json(client, f"har/{a.dev}/env", {
                "v": 1, "seq": seq_env, "t0": t_ms, "dt": 100, "p_pa": [round(float(p), 1) for p in pres[sl][::5]],
                "temp_c": round(29 + rng.normal(0, 0.2), 1), "rh": round(70 + rng.normal(0, 1), 1)})
            seq_imu += 1
            seq_env += 1
            # Bộ phát hiện té bằng ngưỡng như trên ESP32
            for j in range(25):
                r = det.update(t_ms + j * 20, acc[i0 + j], gyr[i0 + j])
                if r:
                    eid = f"{a.dev}-{r['t']}"
                    publish_json(client, f"har/{a.dev}/event", {"v": 1, "id": eid, "type": "suspected", "t": r["t"],
                                                                "peak_g": r["peak_g"]}, qos=1)
                    print(f"  ! suspected {eid} peak={r['peak_g']} g", flush=True)
                    pending = {"id": eid, "t": r["t"], "at": time.time(), "peak_g": r["peak_g"]}
            if pending and time.time() - pending["at"] >= (3 if a.cancel else 10) / a.speed:
                typ = "cancelled" if a.cancel else "confirmed"
                now = int(time.time() * 1000)
                publish_json(client, f"har/{a.dev}/event", {"v": 1, "id": f"{a.dev}-{now}", "type": typ, "t": now,
                                                            "ref": pending["id"], "peak_g": pending["peak_g"]}, qos=1)
                print(f"  ! {typ} {pending['id']}", flush=True)
                pending = None
            if a.sos_after and not sos_sent and time.time() - start > a.sos_after:
                now = int(time.time() * 1000)
                publish_json(client, f"har/{a.dev}/event", {"v": 1, "id": f"{a.dev}-{now}", "type": "sos", "t": now}, qos=1)
                sos_sent = True
            if time.time() - last_status > 10:
                last_status = time.time()
                battery = max(3.3, battery - 0.002)
                publish_json(client, f"har/{a.dev}/status", {"v": 1, "t": t_ms, "online": True, "battery_v": round(battery, 2),
                                                             "rssi": int(-55 + rng.normal(0, 3)),
                                                             "uptime_s": int(time.time() - start), "fw": "fake-1.0"},
                             qos=1, retain=True)
            t_ms += 500
            sleep = (t_ms - int(time.time() * 1000)) / 1000
            if a.speed == 1.0 and sleep > 0:
                time.sleep(sleep)
            elif a.speed != 1.0:
                time.sleep(0.5 / a.speed)
    publish_json(client, f"har/{a.dev}/status", {"v": 1, "online": False}, qos=1, retain=True)
    time.sleep(0.5)
    client.loop_stop()


if __name__ == "__main__":
    main()
