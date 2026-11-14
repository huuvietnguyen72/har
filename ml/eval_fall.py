"""Thí nghiệm D – phát hiện té: ngưỡng trên ESP32 vs model vs kết hợp.

    python eval_fall.py --data data/raw --baro

Với mỗi người (leave-one-subject-out): huấn luyện RF trên những người còn lại, rồi
"phát lại" từng phiên của người đó như thời gian thực:
- ngưỡng   : bộ phát hiện giống firmware (har_edge.fall_threshold)
- model    : quy tắc chỉ-model của har-infer (P(té) ≥ 0,8 rồi nằm ≥ 5 s)
- kết hợp  : đúng logic FallFusion trên Pi (ngưỡng xác nhận + chỉ-model)

Chỉ số: độ nhạy (té được báo trong ±3 s quanh đỉnh), báo động giả/giờ trên phiên
không té, độ đặc hiệu (tỉ lệ phiên không té không có báo động giả), độ trễ phát hiện.
"""
import argparse
from pathlib import Path

import numpy as np

from har_edge import LABELS
from har_edge.fall_threshold import detect_all
from har_edge.features import extract_features
from har_edge.logic import FallFusion, FusionParams, Smoother
from har_ml.dataset import FS, find_fall_peaks, load_recordings, make_windows
from har_ml.evaluate import save
from train_rf import featurize, make_clf

HERE = Path(__file__).resolve().parent


def stream(rec, clf, use_baro: bool, window_s: float, params: FusionParams):
    """Trả (thresh_alerts, model_alerts, combined_alerts) – danh sách thời điểm (ms)."""
    w = int(window_s * FS)
    t = rec.t.astype(np.int64)
    det = detect_all(t, rec.acc, rec.gyr)
    p_full = rec.pressure if rec.pressure is not None else np.zeros(len(t))

    timeline = []  # (thời điểm, loại, dữ liệu)
    sm = Smoother()
    for end in range(w, len(t) + 1, FS):
        s = end - w
        f = extract_features(rec.acc[s:end], rec.gyr[s:end], p_full[s:end] if use_baro else None)[None, :]
        proba = clf.predict_proba(np.nan_to_num(f))[0]
        probs = {LABELS[int(c)]: p for c, p in zip(clf.classes_, proba)}
        raw = max(probs, key=probs.get)
        timeline.append((int(t[end - 1]), "pred", (probs.get("fall", 0.0), sm.update(raw))))
    for k, d in enumerate(det):
        timeline.append((d["t"] + 2000, "event", {"id": f"s{k}", "type": "suspected", "t": d["t"], "peak_g": d["peak_g"]}))
        timeline.append((d["t"] + 12000, "event", {"id": f"c{k}", "type": "confirmed", "t": d["t"] + 12000, "ref": f"s{k}"}))
    timeline.sort(key=lambda x: x[0])

    model_only, combined = FallFusion("eval", params), FallFusion("eval", params)
    m_alerts, c_alerts = [], []
    for now, kind, data in timeline:
        if kind == "pred":
            m_alerts += model_only.on_prediction(now, data[0], data[1], now)
            c_alerts += combined.on_prediction(now, data[0], data[1], now)
        else:
            c_alerts += combined.on_device_event(data, now)
    c_alerts += combined.tick(int(t[-1]) + 60_000)
    return ([d["t"] for d in det],
            [a["t"] for a in m_alerts if a["type"] == "fall"],
            [a["t"] for a in c_alerts if a["type"] == "fall" and not a["cancelled"]])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "raw"))
    ap.add_argument("--baro", dest="baro", action="store_true")
    ap.add_argument("--no-baro", dest="baro", action="store_false")
    ap.set_defaults(baro=True)
    ap.add_argument("--window", type=float, default=2.5)
    ap.add_argument("--p-model-only", type=float, default=0.8)
    ap.add_argument("--p-confirm", type=float, default=0.5)
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()

    recs = load_recordings(a.data)
    params = FusionParams(p_confirm=a.p_confirm, p_model_only=a.p_model_only)
    subjects = sorted({r.subject for r in recs})
    stats = {m: {"tp": 0, "falls": 0, "fa": 0, "adl_recs": 0, "adl_clean": 0, "delays": []}
             for m in ("threshold", "model", "combined")}
    adl_hours = 0.0
    for subj in subjects:
        train = [r for r in recs if r.subject != subj]
        test = [r for r in recs if r.subject == subj]
        win = make_windows(train, a.window)
        clf = make_clf(200, None).fit(featurize(win, a.baro), win.y)
        for rec in test:
            alerts = dict(zip(("threshold", "model", "combined"), stream(rec, clf, a.baro, a.window, params)))
            if rec.activity == "fall":
                peaks = [int(rec.t[p]) for p in find_fall_peaks(rec.acc)]
                for m, ts in alerts.items():
                    for pk in peaks:
                        stats[m]["falls"] += 1
                        hit = [x for x in ts if abs(x - pk) <= 3000]
                        if hit:
                            stats[m]["tp"] += 1
                            stats[m]["delays"].append(min(hit) - pk)
            else:
                adl_hours += (rec.t[-1] - rec.t[0]) / 3_600_000
                for m, ts in alerts.items():
                    stats[m]["fa"] += len(ts)
                    stats[m]["adl_recs"] += 1
                    stats[m]["adl_clean"] += int(len(ts) == 0)
        print(f"  xong người {subj}")

    methods = {}
    for m, s in stats.items():
        methods[m] = {
            "sensitivity": round(s["tp"] / s["falls"], 4) if s["falls"] else None,
            "false_alarms_per_hour": round(s["fa"] / adl_hours, 3) if adl_hours else None,
            "specificity_recordings": round(s["adl_clean"] / s["adl_recs"], 4) if s["adl_recs"] else None,
            "detect_delay_ms_median": float(np.median(s["delays"])) if s["delays"] else None,
            "n_falls": s["falls"], "false_alarms": s["fa"],
        }
        print(f"{m:10} độ nhạy={methods[m]['sensitivity']}  báo động giả/giờ={methods[m]['false_alarms_per_hour']}  "
              f"đặc hiệu={methods[m]['specificity_recordings']}")
    rep = {
        "v": 1, "experiment": "D", "model": "threshold vs rf vs fusion", "features": "imu+baro" if a.baro else "imu",
        "window_s": a.window, "accuracy": None, "macro_f1": None, "f1_per_class": None, "confusion": None,
        "n_windows": None, "n_subjects": len(subjects),
        "extra": {"methods": methods, "adl_hours": round(adl_hours, 3), "p_model_only": a.p_model_only,
                  "p_confirm": a.p_confirm, "cv": "leave-one-subject-out",
                  "synthetic": any(r.synthetic for r in recs),
                  "note": "Thời gian chờ hủy 10 s của ESP32 không tính vào độ trễ phát hiện."},
    }
    print("Đã lưu", save(rep, a.out))


if __name__ == "__main__":
    main()
