"""Tính và lưu metrics.json theo bảng `metrics` trong docs/data-schema.md."""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold

from har_edge import LABELS


EXTERNAL_PREFIX = "SisFall_"  # người của dataset ngoài (xem har_ml/sisfall.py)


def is_external(subject) -> bool:
    return str(subject).startswith(EXTERNAL_PREFIX)


def subject_splits(groups: np.ndarray) -> tuple[list[tuple[np.ndarray, np.ndarray]], np.ndarray]:
    """Leave-one-subject-out chỉ trên người tự thu; người của dataset ngoài luôn nằm trong tập huấn luyện.

    Trả (các cặp (chỉ số huấn luyện, chỉ số kiểm tra), mặt nạ cửa sổ được chấm điểm).
    Mỗi lượt kiểm tra một người tự thu, huấn luyện trên mọi người còn lại (kể cả SisFall),
    nên điểm số chỉ phản ánh người đeo bộ har01 thật.
    """
    groups = np.asarray(groups)
    ext = np.array([is_external(g) for g in groups], dtype=bool)
    own = sorted(set(groups[~ext].tolist()))
    if len(own) < 2:
        raise ValueError("Cần ít nhất 2 người tự thu để chia tập theo người")
    splits = [(np.where(groups != s)[0], np.where(groups == s)[0]) for s in own]
    return splits, ~ext


def cv_description(groups: np.ndarray) -> str:
    groups = np.asarray(groups)
    ext = np.array([is_external(g) for g in groups], dtype=bool)
    own = len(set(groups[~ext].tolist()))
    s = f"leave-one-subject-out trên {own} người tự thu, dự đoán out-of-fold"
    if ext.any():
        s += (f"; mỗi lượt huấn luyện thêm SisFall ({len(set(groups[ext].tolist()))} người, "
              f"{int(ext.sum())} cửa sổ), không chấm điểm trên SisFall")
    return s


def external_info(groups: np.ndarray) -> dict:
    groups = np.asarray(groups)
    ext = np.array([is_external(g) for g in groups], dtype=bool)
    return {"SisFall": {"subjects": len(set(groups[ext].tolist())), "windows": int(ext.sum())}} if ext.any() else {}


def group_folds(groups: np.ndarray, max_splits: int = 5) -> GroupKFold:
    """Chia theo người: không bao giờ để cửa sổ của cùng một người vừa ở tập huấn luyện vừa ở tập kiểm tra."""
    k = min(max_splits, len(set(groups)))
    if k < 2:
        raise ValueError("Cần ít nhất 2 người để chia tập theo người")
    return GroupKFold(n_splits=k)


def report(experiment: str, model_name: str, features: str, window_s: float, y_true, y_pred,
           n_subjects: int, extra: dict | None = None) -> dict:
    present = sorted(set(np.asarray(y_true)) | set(np.asarray(y_pred)))
    labels = [LABELS[i] for i in present]
    f1s = f1_score(y_true, y_pred, labels=present, average=None, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=present)
    return {
        "v": 1,
        "experiment": experiment,
        "model": model_name,
        "features": features,
        "window_s": window_s,
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=present, average="macro", zero_division=0)), 4),
        "f1_per_class": {lbl: round(float(f), 4) for lbl, f in zip(labels, f1s)},
        "confusion": {"labels": labels, "matrix": cm.tolist()},
        "n_windows": int(len(y_true)),
        "n_subjects": int(n_subjects),
        "extra": {**(extra or {}), "created": datetime.now(timezone.utc).isoformat(timespec="seconds")},
    }


def save(rep: dict, out_dir: str | Path) -> Path:
    d = Path(out_dir) / rep["experiment"]
    d.mkdir(parents=True, exist_ok=True)
    path = d / "metrics.json"
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def print_report(rep: dict) -> None:
    print(f"\n== {rep['experiment']} · {rep['model']} · {rep['features']} · cửa sổ {rep['window_s']} s")
    print(f"accuracy={rep['accuracy']:.3f}  macro-F1={rep['macro_f1']:.3f}  "
          f"({rep['n_windows']} cửa sổ, {rep['n_subjects']} người)")
    print("F1: " + "  ".join(f"{k}={v:.2f}" for k, v in rep["f1_per_class"].items()))
