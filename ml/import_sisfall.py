"""Chuyển SisFall (.npy hoặc .txt gốc) sang định dạng phiên của dự án (xem har_ml/sisfall.py).

    python import_sisfall.py                                   # data/external/SisFall -> data/external/sisfall_sessions
    python import_sisfall.py --subjects SA01,SA02 --no-adl     # chỉ vài người, bỏ hoạt động không dùng huấn luyện

Huấn luyện cùng dữ liệu tự thu: --data "data/raw,data/external/sisfall_sessions".
"""
import argparse
import collections
from pathlib import Path

import numpy as np

from har_ml.sisfall import convert, label_of, parse_name, subject_rotation, write_session

HERE = Path(__file__).resolve().parent
T_BASE = 1_400_000_000_000  # mốc thời gian giả (2014) để không trùng dữ liệu thật


def load_raw(path: Path) -> np.ndarray:
    if path.suffix == ".npy":
        return np.load(path, allow_pickle=False)
    # bản gốc: 9 số nguyên mỗi dòng, ngăn bằng dấu phẩy, kết thúc bằng ';'
    rows = [l.replace(";", "").strip() for l in path.read_text(encoding="latin-1").splitlines()]
    return np.array([[int(x) for x in r.split(",")] for r in rows if r], dtype=np.int64)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(HERE / "data" / "external" / "SisFall"))
    ap.add_argument("--out", default=str(HERE / "data" / "external" / "sisfall_sessions"))
    ap.add_argument("--subjects", default="", help="vd SA01,SE06; bỏ trống = tất cả")
    ap.add_argument("--no-adl", action="store_true", help="chỉ ghi phiên có nhãn (walk, fall)")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    files = sorted(p for p in src.glob("S*/*") if p.suffix in (".npy", ".txt"))
    by_subj: dict[str, list[Path]] = collections.defaultdict(list)
    for p in files:
        by_subj[parse_name(p.name)[1]].append(p)
    want = {s.strip() for s in a.subjects.split(",") if s.strip()}
    count = collections.Counter()
    n = 0
    for subj in sorted(by_subj):
        if want and subj not in want:
            continue
        paths = by_subj[subj]
        walks = [p for p in paths if parse_name(p.name)[0] == "D01"] or [p for p in paths if parse_name(p.name)[0] == "D02"]
        if not walks:
            print(f"{subj}: không có lượt đi bộ D01/D02 để căn hướng, bỏ qua")
            continue
        gravity, rot = subject_rotation([load_raw(p) for p in walks])
        for p in paths:
            code, _, trial = parse_name(p.name)
            label = label_of(code)
            if a.no_adl and label == "adl":
                continue
            acc, gyr = convert(load_raw(p), rot)
            write_session(out, code, subj, trial, acc, gyr, T_BASE + n * 10_000_000, gravity)
            n += 1
            count[label] += 1
        print(f"{subj}: trọng lực khi đi bộ {np.round(gravity, 3)} g -> xoay về hệ trục bộ đeo")
    print(f"Đã ghi {n} phiên vào {out}: {dict(count)}")


if __name__ == "__main__":
    main()
