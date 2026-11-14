"""Sinh dataset GIẢ LẬP đúng định dạng phiên thu của har-ingest, để kiểm tra code
huấn luyện/đánh giá khi chưa thu dữ liệu thật.

    python make_synthetic.py --out data/synthetic --subjects 5

Mọi phiên có "synthetic": true trong meta.json, và metrics.json sinh từ đó cũng ghi
extra.synthetic = true. KHÔNG dùng các số này trong báo cáo.
"""
import argparse
import json
from pathlib import Path

import numpy as np

import har_ml  # noqa: F401  (UTF-8 console)
from har_edge import LABELS
from har_edge.synth import generate

PLAN = {"stand": (3, 60), "sit": (3, 60), "lie": (3, 60), "walk": (3, 60), "run": (2, 60),
        "stairs_up": (4, 30), "stairs_down": (4, 30), "fall": (8, 10)}  # (số phiên, giây mỗi phiên)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--subjects", type=int, default=5)
    ap.add_argument("--scale", type=float, default=1.0, help="nhân thời lượng mỗi phiên")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    t = 1_763_000_000_000
    n = 0
    for s in range(1, a.subjects + 1):
        subj = f"S{s:02d}"
        scale = rng.uniform(0.9, 1.1)
        for act in LABELS:
            reps, dur = PLAN[act]
            for k in range(reps):
                d = 4 + 6 if act == "fall" else dur * a.scale
                acc, gyr, p = generate(act, d, rng, p0=rng.uniform(100_500, 101_200), subject_scale=scale)
                sid = f"{subj}_{act}_{k:02d}"
                folder = out / sid
                folder.mkdir(parents=True, exist_ok=True)
                ts = t + np.arange(len(acc)) * 20
                imu = np.column_stack([ts, acc, gyr])
                np.savetxt(folder / "imu.csv", imu, delimiter=",", header="t,ax,ay,az,gx,gy,gz", comments="",
                           fmt=["%d"] + ["%.5f"] * 6)
                env = np.column_stack([ts[::5], p[::5]])
                np.savetxt(folder / "env.csv", env, delimiter=",", header="t,p_pa", comments="", fmt=["%d", "%.2f"])
                meta = {"id": sid, "dev": "har01", "subject": subj, "activity": act, "start": int(ts[0]),
                        "end": int(ts[-1]), "synthetic": True}
                (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                t += int(d * 1000) + 60_000
                n += 1
    print(f"Đã sinh {n} phiên giả lập ở {out}")


if __name__ == "__main__":
    main()
