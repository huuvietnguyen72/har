"""Đọc phiên thu (định dạng của har-ingest) và cắt cửa sổ có nhãn.

Mỗi phiên: <root>/<id>/imu.csv, env.csv, meta.json (subject, activity).

Làm sạch theo kế hoạch:
1. Cắt bỏ 2 s đầu và 2 s cuối mỗi phiên.
2. Phiên té: tìm đỉnh SVM; đoạn [đỉnh - 1,5 s, đỉnh + 1 s] là "fall"; phần nằm yên sau đó là "lie";
   phần trước khi té bị bỏ.
3. Áp suất: nội suy lên 50 Hz, lọc thông thấp; đặc trưng dùng hiệu áp (Pa/s).
4. Cửa sổ 2,5 s (125 mẫu) chồng lấn 50 %. Cửa sổ té lấy dày hơn quanh đỉnh (bước 0,1 s).
"""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from har_edge import LABELS
from har_edge.features import smooth_pressure

FS = 50
TRIM_S = 2.0


@dataclass
class Recording:
    id: str
    subject: str
    activity: str
    t: np.ndarray  # ms
    acc: np.ndarray  # (n,3) g
    gyr: np.ndarray  # (n,3) °/s
    pressure: np.ndarray | None  # (n,) Pa, đã nội suy + lọc
    synthetic: bool = False


@dataclass
class Windows:
    acc: np.ndarray  # (N, n, 3)
    gyr: np.ndarray  # (N, n, 3)
    pressure: np.ndarray  # (N, n)  (0 nếu thiếu BMP280)
    y: np.ndarray  # (N,) chỉ số nhãn trong LABELS
    groups: np.ndarray  # (N,) mã người
    rec_ids: np.ndarray  # (N,) id phiên
    window_s: float

    def __len__(self) -> int:
        return len(self.y)

    @property
    def n_subjects(self) -> int:
        return len(set(self.groups))


def load_recordings(root: str | Path) -> list[Recording]:
    recs = []
    for meta_path in sorted(Path(root).rglob("meta.json")):
        d = meta_path.parent
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("activity") not in LABELS or not (d / "imu.csv").exists():
            continue
        imu = pd.read_csv(d / "imu.csv").drop_duplicates("t").sort_values("t")
        if len(imu) < FS * (2 * TRIM_S + 2.5):
            continue
        t = imu["t"].to_numpy(dtype=np.float64)
        pressure = None
        if (d / "env.csv").exists():
            env = pd.read_csv(d / "env.csv").dropna().drop_duplicates("t").sort_values("t")
            if len(env) >= 2:
                pressure = smooth_pressure(np.interp(t, env["t"].to_numpy(), env["p_pa"].to_numpy()))
        recs.append(Recording(
            id=meta.get("id", d.name), subject=str(meta.get("subject") or "S00"), activity=meta["activity"],
            t=t, acc=imu[["ax", "ay", "az"]].to_numpy(), gyr=imu[["gx", "gy", "gz"]].to_numpy(),
            pressure=pressure, synthetic=bool(meta.get("synthetic", False)),
        ))
    return recs


def find_fall_peaks(acc: np.ndarray, min_g: float = 2.0, min_gap_s: float = 5.0) -> list[int]:
    svm = np.linalg.norm(acc, axis=1)
    peaks: list[int] = []
    for i in np.argsort(-svm):
        if svm[i] < min_g:
            break
        if all(abs(i - p) > min_gap_s * FS for p in peaks):
            peaks.append(int(i))
    return sorted(peaks)


def _segments(rec: Recording, window_s: float) -> list[tuple[int, int, str, int]]:
    """Trả các đoạn (i_bắt_đầu, i_kết_thúc, nhãn, bước) để cắt cửa sổ."""
    n = len(rec.t)
    w = int(window_s * FS)
    trim = int(TRIM_S * FS)
    if rec.activity != "fall":
        return [(trim, n - trim, rec.activity, w // 2)]
    out = []
    peaks = find_fall_peaks(rec.acc)
    for k, p in enumerate(peaks):
        # cửa sổ té: chứa đỉnh, đỉnh cách hai mép ít nhất ~0,5 s (bước 0,1 s)
        lo = max(0, p - w + int(0.5 * FS))
        hi = min(n, p + w - int(0.5 * FS))
        out.append((lo, hi, "fall", int(0.1 * FS)))
        # phần nằm yên sau té -> lie (đến đỉnh kế tiếp hoặc cuối phiên)
        end = peaks[k + 1] - int(2 * FS) if k + 1 < len(peaks) else n - trim
        out.append((p + int(1.0 * FS), end, "lie", w // 2))
    return out


def make_windows(recs: list[Recording], window_s: float = 2.5) -> Windows:
    w = int(round(window_s * FS))
    A, G, P, Y, GR, R = [], [], [], [], [], []
    for rec in recs:
        p_full = rec.pressure if rec.pressure is not None else np.zeros(len(rec.t))
        for lo, hi, label, step in _segments(rec, window_s):
            for s in range(lo, hi - w + 1, step):
                A.append(rec.acc[s:s + w])
                G.append(rec.gyr[s:s + w])
                P.append(p_full[s:s + w])
                Y.append(LABELS.index(label))
                GR.append(rec.subject)
                R.append(rec.id)
    if not A:
        raise ValueError("Không cắt được cửa sổ nào — kiểm tra thư mục dữ liệu")
    return Windows(np.asarray(A, np.float32), np.asarray(G, np.float32), np.asarray(P, np.float32),
                   np.asarray(Y), np.asarray(GR), np.asarray(R), window_s)


def summary(win: Windows) -> pd.DataFrame:
    df = pd.DataFrame({"label": [LABELS[i] for i in win.y], "subject": win.groups})
    return df.pivot_table(index="label", columns="subject", aggfunc="size", fill_value=0)
