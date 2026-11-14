"""Phát lại một phiên thu đã ghi lên MQTT, giống hệt gói của ESP32, để thử toàn tuyến
mà không cần đeo thiết bị.

    python replay.py data/sessions/har01_S01_walk_20261120-101500
    python replay.py data/sessions/<id> --speed 4 --dev har09
    python replay.py data/sessions/<id> --keep-time     # giữ thời gian gốc (mặc định dời về hiện tại)
"""
import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from har_edge.config import load_config
from har_edge.mqtt import make_client, publish_json
from har_edge.units import to_raw_acc, to_raw_gyro


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", type=Path)
    ap.add_argument("--dev", default=None, help="mặc định lấy từ meta.json hoặc har01")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--keep-time", action="store_true")
    a = ap.parse_args()

    imu = pd.read_csv(a.session_dir / "imu.csv")
    env_path = a.session_dir / "env.csv"
    env = pd.read_csv(env_path) if env_path.exists() else pd.DataFrame(columns=["t", "p_pa"])
    dev = a.dev
    if dev is None:
        import json

        meta = a.session_dir / "meta.json"
        dev = json.loads(meta.read_text(encoding="utf-8")).get("dev", "har01") if meta.exists() else "har01"

    cfg = load_config()
    client = make_client(cfg, "har-replay", [])
    client.loop_start()
    time.sleep(1)

    shift = 0 if a.keep_time else int(time.time() * 1000) - int(imu["t"].iloc[0])
    t_env = env["t"].to_numpy()
    p_env = env["p_pa"].to_numpy()
    wall0 = time.time()
    seq = 0
    for i0 in range(0, len(imu) - 24, 25):
        chunk = imu.iloc[i0:i0 + 25]
        ra = to_raw_acc(chunk[["ax", "ay", "az"]].to_numpy())
        rg = to_raw_gyro(chunk[["gx", "gy", "gz"]].to_numpy())
        t0 = int(chunk["t"].iloc[0])
        publish_json(client, f"har/{dev}/imu", {
            "v": 1, "seq": seq, "t0": t0 + shift, "dt": 20, "replay": False,
            "ax": ra[:, 0].tolist(), "ay": ra[:, 1].tolist(), "az": ra[:, 2].tolist(),
            "gx": rg[:, 0].tolist(), "gy": rg[:, 1].tolist(), "gz": rg[:, 2].tolist()})
        mask = (t_env >= t0) & (t_env < t0 + 500)
        if mask.any():
            publish_json(client, f"har/{dev}/env", {"v": 1, "seq": seq, "t0": int(t_env[mask][0]) + shift, "dt": 100,
                                                     "p_pa": np.round(p_env[mask], 1).tolist()})
        seq += 1
        target = wall0 + (i0 / 50) / a.speed
        if target > time.time():
            time.sleep(target - time.time())
    print(f"Đã phát {seq} gói ({len(imu) / 50:.0f} s dữ liệu)")
    time.sleep(0.5)
    client.loop_stop()


if __name__ == "__main__":
    main()
