"""Model 2 – 1D-CNN (thí nghiệm B1/B2), xuất TFLite float32 và int8.

    python train_cnn.py --data data/raw --experiment B1 --no-baro
    python train_cnn.py --data data/raw --experiment B2 --baro --export

Kiến trúc: 3 khối Conv1D (32, 64, 64 bộ lọc, kernel 5, BatchNorm, ReLU, MaxPool)
→ GlobalAveragePooling → Dense 64 + Dropout 0,3 → Softmax 8 lớp.
Chuẩn hóa theo tập huấn luyện, class weight, early stopping. Đánh giá GroupKFold theo người.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from har_edge import LABELS
from har_edge.features import cnn_input
from har_ml.dataset import load_recordings, make_windows, summary
from har_ml.evaluate import group_folds, print_report, report, save

HERE = Path(__file__).resolve().parent


def build_inputs(win, use_baro: bool) -> np.ndarray:
    return np.stack([cnn_input(win.acc[i], win.gyr[i], win.pressure[i] if use_baro else None) for i in range(len(win))])


def build_model(n_steps: int, n_ch: int, n_classes: int = len(LABELS)):
    import tensorflow as tf
    from tensorflow.keras import layers

    inp = layers.Input((n_steps, n_ch))
    x = inp
    for filters in (32, 64, 64):
        x = layers.Conv1D(filters, 5, padding="same", use_bias=False)(x)
        x = layers.BatchNormalization()(x)
        x = layers.ReLU()(x)
        x = layers.MaxPooling1D(2)(x)
    x = layers.GlobalAveragePooling1D()(x)
    x = layers.Dense(64, activation="relu")(x)
    x = layers.Dropout(0.3)(x)
    out = layers.Dense(n_classes, activation="softmax")(x)
    model = tf.keras.Model(inp, out)
    model.compile(optimizer=tf.keras.optimizers.Adam(1e-3), loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    return model


def class_weights(y: np.ndarray) -> dict[int, float]:
    counts = np.bincount(y, minlength=len(LABELS)).astype(float)
    present = counts > 0
    w = np.zeros_like(counts)
    w[present] = counts[present].sum() / (present.sum() * counts[present])
    return {i: float(w[i]) for i in range(len(LABELS)) if present[i]}


def fit(X, y, epochs: int, seed: int = 42):
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)
    mean = X.reshape(-1, X.shape[-1]).mean(axis=0)
    std = X.reshape(-1, X.shape[-1]).std(axis=0) + 1e-6
    Xn = (X - mean) / std
    model = build_model(X.shape[1], X.shape[2])
    cb = [tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=6, restore_best_weights=True)]
    model.fit(Xn, y, validation_split=0.15, epochs=epochs, batch_size=64, class_weight=class_weights(y),
              callbacks=cb, verbose=0, shuffle=True)
    return model, mean.astype(np.float32), std.astype(np.float32)


def export_tflite(model, X_norm_sample: np.ndarray, out_dir: Path) -> dict[str, Path]:
    import tensorflow as tf

    paths = {}
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    paths["float"] = out_dir / "model_float.tflite"
    paths["float"].write_bytes(conv.convert())

    def rep_data():
        for i in range(min(300, len(X_norm_sample))):
            yield [X_norm_sample[i:i + 1].astype(np.float32)]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep_data
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    paths["int8"] = out_dir / "model_int8.tflite"
    paths["int8"].write_bytes(conv.convert())
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "raw"))
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--baro", dest="baro", action="store_true")
    ap.add_argument("--no-baro", dest="baro", action="store_false")
    ap.set_defaults(baro=True)
    ap.add_argument("--window", type=float, default=2.5)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()

    recs = load_recordings(a.data)
    synthetic = any(r.synthetic for r in recs)
    win = make_windows(recs, a.window)
    print(f"{len(recs)} phiên, {len(win)} cửa sổ, {win.n_subjects} người")
    print(summary(win))
    X = build_inputs(win, a.baro)
    y, groups = win.y, win.groups
    cv = group_folds(groups)

    pred = np.empty_like(y)
    for k, (tr, te) in enumerate(cv.split(X, y, groups)):
        model, mean, std = fit(X[tr], y[tr], a.epochs, seed=42 + k)
        pred[te] = model.predict((X[te] - mean) / std, verbose=0).argmax(axis=1)
        print(f"  fold {k + 1}/{cv.n_splits}: người kiểm tra {sorted(set(groups[te]))}")

    feats = "imu+baro" if a.baro else "imu"
    name = f"cnn-{feats}-{a.window:g}s-{a.version}"
    extra = {"cv": f"GroupKFold k={cv.n_splits} theo người, dự đoán out-of-fold", "epochs_max": a.epochs,
             "synthetic": synthetic}

    if a.export:
        model, mean, std = fit(X, y, a.epochs)
        d = HERE / "models" / name
        d.mkdir(parents=True, exist_ok=True)
        paths = export_tflite(model, (X - mean) / std, d)
        extra["tflite_kb"] = {k: round(p.stat().st_size / 1024, 1) for k, p in paths.items()}
        # độ trễ int8 trên máy này (đo lại trên Pi bằng tflite-runtime)
        import tensorflow as tf

        it = tf.lite.Interpreter(model_path=str(paths["int8"]))
        it.allocate_tensors()
        inp = it.get_input_details()[0]
        t0 = time.perf_counter()
        for _ in range(50):
            it.set_tensor(inp["index"], np.zeros(inp["shape"], np.int8))
            it.invoke()
        extra["infer_ms_train_machine_int8"] = round((time.perf_counter() - t0) / 50 * 1000, 2)
        for variant, fname in (("int8", "model_int8.tflite"), ("float", "model_float.tflite")):
            meta = {"name": name if variant == "int8" else f"{name}-float", "type": "tflite", "file": fname,
                    "labels": LABELS, "use_baro": a.baro, "window_s": a.window, "fs": 50,
                    "norm": {"mean": mean.tolist(), "std": std.tolist()}, "experiment": a.experiment}
            target = d / ("meta.json" if variant == "int8" else "meta_float.json")
            target.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã xuất model -> {d}  (meta.json dùng bản int8; đổi tên meta_float.json để dùng bản float)")

    rep = report(a.experiment, name, feats, a.window, y, pred, win.n_subjects, extra=extra)
    print_report(rep)
    print("Đã lưu", save(rep, a.out))


if __name__ == "__main__":
    main()
