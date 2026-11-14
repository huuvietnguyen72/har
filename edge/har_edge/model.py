"""Nạp model để suy luận trên Pi.

Thư mục model (MODEL_DIR, mặc định edge/models/current/) chứa meta.json do ml/ xuất ra:

    {"name": "rf-imu+baro-v1", "type": "rf", "file": "model.joblib",
     "labels": [...8 nhãn...], "use_baro": true, "window_s": 2.5, "fs": 50}
    {"name": "cnn-imu+baro-v1", "type": "tflite", "file": "model_int8.tflite",
     "labels": [...], "use_baro": true, "window_s": 2.5, "fs": 50,
     "norm": {"mean": [...], "std": [...]}}

Không có thư mục model thì dùng HeuristicModel (luật đơn giản) để chạy thử toàn tuyến.
"""
import json
import logging
from pathlib import Path

import numpy as np

from . import LABELS
from .features import cnn_input, extract_features, tilt_deg

log = logging.getLogger(__name__)


class BaseModel:
    name = "base"
    labels: list[str] = LABELS
    use_baro = False
    window_s = 2.5
    fs = 50

    @property
    def n_samples(self) -> int:
        return int(round(self.window_s * self.fs))

    def predict_proba(self, acc: np.ndarray, gyr: np.ndarray, pressure: np.ndarray | None) -> dict[str, float]:
        raise NotImplementedError


class RFModel(BaseModel):
    def __init__(self, path: Path, meta: dict):
        import joblib

        self.clf = joblib.load(path)
        self.name = meta["name"]
        self.labels = meta["labels"]
        self.use_baro = bool(meta.get("use_baro"))
        self.window_s = float(meta.get("window_s", 2.5))
        self.fs = int(meta.get("fs", 50))
        self._classes = [self.labels[int(c)] if not isinstance(c, str) else c for c in self.clf.classes_]

    def predict_proba(self, acc, gyr, pressure):
        x = extract_features(acc, gyr, pressure if self.use_baro else None, self.fs)[None, :]
        x = np.nan_to_num(x)
        p = self.clf.predict_proba(x)[0]
        out = {lbl: 0.0 for lbl in self.labels}
        out.update({c: float(v) for c, v in zip(self._classes, p)})
        return out


class TFLiteModel(BaseModel):
    def __init__(self, path: Path, meta: dict):
        try:
            from tflite_runtime.interpreter import Interpreter
        except ImportError:  # trên laptop dùng TensorFlow đầy đủ
            from tensorflow.lite import Interpreter  # type: ignore
        self.interp = Interpreter(model_path=str(path), num_threads=2)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]
        self.name = meta["name"]
        self.labels = meta["labels"]
        self.use_baro = bool(meta.get("use_baro"))
        self.window_s = float(meta.get("window_s", 2.5))
        self.fs = int(meta.get("fs", 50))
        self.mean = np.asarray(meta["norm"]["mean"], dtype=np.float32)
        self.std = np.asarray(meta["norm"]["std"], dtype=np.float32)

    def predict_proba(self, acc, gyr, pressure):
        x = (cnn_input(acc, gyr, pressure if self.use_baro else None) - self.mean) / self.std
        x = x[None, ...].astype(np.float32)
        if self.inp["dtype"] == np.int8:  # model lượng tử hóa int8
            scale, zero = self.inp["quantization"]
            x = np.clip(np.round(x / scale + zero), -128, 127).astype(np.int8)
        self.interp.set_tensor(self.inp["index"], x)
        self.interp.invoke()
        y = self.interp.get_tensor(self.out["index"])[0]
        if self.out["dtype"] == np.int8:
            scale, zero = self.out["quantization"]
            y = (y.astype(np.float32) - zero) * scale
        y = np.clip(y, 0, None)
        y = y / y.sum() if y.sum() > 0 else np.full(len(y), 1 / len(y))
        return {lbl: float(v) for lbl, v in zip(self.labels, y)}


class HeuristicModel(BaseModel):
    """Luật đơn giản, chỉ để chạy thử toàn tuyến trước khi có model thật."""

    name = "heuristic-v1"
    use_baro = True

    def predict_proba(self, acc, gyr, pressure):
        svm = np.linalg.norm(acc, axis=1)
        tilt = float(tilt_deg(acc.mean(axis=0)[None, :])[0])
        std = float(svm.std())
        slope = 0.0
        if pressure is not None and np.all(np.isfinite(pressure)):
            slope = float(np.polyfit(np.arange(len(pressure)) / self.fs, pressure, 1)[0])
        if svm.max() > 2.5 and svm.min() < 0.5:
            label = "fall"
        elif std < 0.06:
            label = "lie" if tilt > 65 else ("sit" if tilt > 25 else "stand")
        elif std < 0.45:
            label = "stairs_up" if slope < -1.2 else ("stairs_down" if slope > 1.2 else "walk")
        else:
            label = "run"
        probs = {lbl: 0.3 / (len(LABELS) - 1) for lbl in LABELS}
        probs[label] = 0.7
        return probs


def load_model(model_dir: Path) -> BaseModel:
    meta_path = Path(model_dir) / "meta.json"
    if not meta_path.exists():
        log.warning("Không thấy %s — dùng HeuristicModel", meta_path)
        return HeuristicModel()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    path = Path(model_dir) / meta["file"]
    kind = meta.get("type", "rf")
    model = RFModel(path, meta) if kind == "rf" else TFLiteModel(path, meta)
    log.info("Đã nạp model %s (%s, baro=%s)", model.name, kind, model.use_baro)
    return model
