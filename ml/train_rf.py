"""Model 1 – Random Forest trên đặc trưng thống kê (thí nghiệm A1/A2, C).

    python train_rf.py --data data/raw --experiment A1 --no-baro
    python train_rf.py --data data/raw --experiment A2 --baro --export
    python train_rf.py --data data/raw --experiment C_2.0 --baro --window 2.0

- Chọn n_estimators, max_depth bằng GroupKFold theo người.
- Báo cáo dự đoán out-of-fold (mỗi cửa sổ được dự đoán bởi model chưa thấy người đó).
- --export: huấn luyện lại trên toàn bộ dữ liệu, lưu models/<tên>/ (meta.json + model.joblib)
  để chép sang edge/models/current/.
"""
import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score

from har_edge import LABELS
from har_edge.features import extract_features, feature_names
from har_ml.dataset import load_recordings, make_windows, summary
from har_ml.evaluate import group_folds, print_report, report, save

HERE = Path(__file__).resolve().parent
GRID = [(200, None), (200, 20), (400, None), (100, 12)]


def featurize(win, use_baro: bool) -> np.ndarray:
    return np.nan_to_num(np.stack([
        extract_features(win.acc[i], win.gyr[i], win.pressure[i] if use_baro else None) for i in range(len(win))
    ]))


def make_clf(n_estimators, max_depth, seed=42):
    return RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, class_weight="balanced",
                                  min_samples_leaf=2, n_jobs=-1, random_state=seed)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "raw"))
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--baro", dest="baro", action="store_true")
    ap.add_argument("--no-baro", dest="baro", action="store_false")
    ap.set_defaults(baro=True)
    ap.add_argument("--window", type=float, default=2.5)
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()

    recs = load_recordings(a.data)
    synthetic = any(r.synthetic for r in recs)
    win = make_windows(recs, a.window)
    print(f"{len(recs)} phiên, {len(win)} cửa sổ, {win.n_subjects} người")
    print(summary(win))
    X = featurize(win, a.baro)
    y, groups = win.y, win.groups
    cv = group_folds(groups)

    best, best_f1, best_pred = None, -1.0, None
    for n_est, depth in GRID:
        pred = np.empty_like(y)
        for tr, te in cv.split(X, y, groups):
            clf = make_clf(n_est, depth).fit(X[tr], y[tr])
            pred[te] = clf.predict(X[te])
        f1 = f1_score(y, pred, average="macro")
        print(f"  n_estimators={n_est:<4} max_depth={str(depth):<5} macro-F1={f1:.3f}")
        if f1 > best_f1:
            best, best_f1, best_pred = (n_est, depth), f1, pred

    feats = "imu+baro" if a.baro else "imu"
    name = f"rf-{feats}-{a.window:g}s-{a.version}"
    final = make_clf(*best).fit(X, y)

    # Độ trễ suy luận một cửa sổ (đặc trưng + dự đoán) trên máy này; đo lại trên Pi
    t0 = time.perf_counter()
    for i in range(50):
        final.predict_proba(extract_features(win.acc[i], win.gyr[i], win.pressure[i] if a.baro else None)[None, :])
    infer_ms = (time.perf_counter() - t0) / 50 * 1000

    names = feature_names(a.baro)
    imp = sorted(zip(names, final.feature_importances_), key=lambda kv: -kv[1])[:15]
    rep = report(a.experiment, name, feats, a.window, y, best_pred, win.n_subjects, extra={
        "cv": f"GroupKFold k={cv.n_splits} theo người, dự đoán out-of-fold",
        "params": {"n_estimators": best[0], "max_depth": best[1]},
        "infer_ms_train_machine": round(infer_ms, 2),
        "feature_importance": {k: round(float(v), 4) for k, v in imp},
        "synthetic": synthetic,
    })
    print_report(rep)
    print("Đặc trưng quan trọng nhất:", ", ".join(f"{k} ({v:.3f})" for k, v in imp[:8]))
    print("Đã lưu", save(rep, a.out))

    if a.export:
        d = HERE / "models" / name
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(final, d / "model.joblib", compress=3)
        meta = {"name": name, "type": "rf", "file": "model.joblib", "labels": LABELS, "use_baro": a.baro,
                "window_s": a.window, "fs": 50, "features": names, "experiment": a.experiment}
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã xuất model -> {d}  (chép vào edge/models/current/)")


if __name__ == "__main__":
    main()
