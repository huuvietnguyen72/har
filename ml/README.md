# ML – dataset và huấn luyện

Huấn luyện trên laptop hoặc Google Colab, chỉ suy luận trên Pi. Thiết kế ở kế hoạch, giai đoạn 4.
Đặc trưng lấy từ [`../edge/har_edge/features.py`](../edge/har_edge/features.py) — **cùng một file** với lúc suy luận trên Pi, nên không thể lệch nhau.

## Cài đặt

```bash
cd ml
python -m venv .venv && .venv/Scripts/activate     # Linux/macOS: source .venv/bin/activate
pip install -e ../edge -r requirements.txt
```

## Dữ liệu

- Chép thư mục `edge/data/sessions/` từ Pi vào `ml/data/raw/` (đã nằm trong `.gitignore`; bản gốc để ở Google Drive của nhóm).
- Mỗi phiên: `imu.csv`, `env.csv`, `meta.json` (`subject`, `activity`) — do `record.py` + `har-ingest` tạo.
- Làm sạch (`har_ml/dataset.py`): cắt 2 s đầu/cuối; phiên té tìm đỉnh SVM, đoạn quanh đỉnh là `fall`, phần nằm yên sau đó là `lie`; áp suất nội suy lên 50 Hz rồi lọc thông thấp; cửa sổ 2,5 s chồng lấn 50 %.
- **Chia tập theo người** (GroupKFold); không bao giờ chia ngẫu nhiên theo cửa sổ.

## Thí nghiệm

| Lệnh | Thí nghiệm |
| --- | --- |
| `python train_rf.py --experiment A1 --no-baro` | RF chỉ IMU |
| `python train_rf.py --experiment A2 --baro --export` | RF IMU + BMP280, xuất model |
| `python train_cnn.py --experiment B1 --no-baro` | 1D-CNN chỉ IMU |
| `python train_cnn.py --experiment B2 --baro --export` | 1D-CNN IMU + BMP280, xuất TFLite float + int8 |
| `python train_rf.py --experiment C --baro --window 2.0` | Cửa sổ 2,0 s (so với A2 2,5 s) |
| `python eval_fall.py --baro` | D: ngưỡng ESP32 vs model vs kết hợp (leave-one-subject-out) |
| `python run_experiments.py` | Chạy tất cả |

Mỗi thí nghiệm ghi `results/<thí nghiệm>/metrics.json` (accuracy, macro-F1, F1 từng lớp, ma trận nhầm lẫn, số cửa sổ, số người, phiên bản model). Đẩy lên VPS để trang **Đánh giá model** hiển thị:

```bash
python push_metrics.py                       # đọc VPS_API_URL, VPS_DEVICE_KEY từ edge/.env
python push_metrics.py --system pin.json     # số liệu hệ thống, ví dụ [{"dev":"har01","day":"2026-12-01","battery_hours":16.2}]
```

## Đưa model lên Pi

`--export` tạo `models/<tên>/` gồm `meta.json` và `model.joblib` (RF) hoặc `model_int8.tflite` (CNN). Chép cả thư mục vào `edge/models/current/` trên Pi rồi `sudo systemctl restart har-infer`. Trên Pi cài `tflite-runtime` hoặc `ai-edge-litert` khi dùng CNN.

## Thử code khi chưa có dữ liệu thật

```bash
python make_synthetic.py --out data/synthetic --subjects 5 --scale 0.5
python run_experiments.py --data data/synthetic --epochs 15
```

Dữ liệu giả lập dễ tách nên điểm gần như 1,0 — **vô nghĩa**, chỉ để kiểm tra code chạy đúng. Các file kết quả từ đó có `"synthetic": true`; `push_metrics.py` từ chối đẩy chúng lên cloud (trừ khi thêm `--allow-synthetic`) và web app gắn nhãn "giả lập".
