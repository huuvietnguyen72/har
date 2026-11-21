# ML – dataset và huấn luyện

Huấn luyện trên laptop hoặc Google Colab, chỉ suy luận trên Pi. Kế hoạch: [`docs/ke-hoach.md`](../docs/ke-hoach.md).
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
- **Chia tập theo người** (leave-one-subject-out); không bao giờ chia ngẫu nhiên theo cửa sổ.

### Dataset ngoài: SisFall

Bổ sung té (và đi bộ) từ SisFall — Sucerquia, López, Vargas-Bonilla, *SisFall: A Fall and Movement Dataset*, Sensors 17(1):198, 2017, doi:[10.3390/s17010198](https://doi.org/10.3390/s17010198). **Phải trích dẫn bài báo này trong báo cáo.** 38 người (SA01–SA23 19–30 tuổi, SE01–SE15 60–75 tuổi; người cao tuổi chỉ thu hoạt động thường ngày, trừ SE06), thiết bị ở thắt lưng, 200 Hz.

```bash
# trang gốc (sistemic.udea.edu.co) không truy cập được lúc tải; dùng bản sao .npy (giữ nguyên số đo thô + Readme gốc)
git clone --depth 1 https://gitee.com/yuxiqin/imu-fall-database.git data/external/SisFall
python import_sisfall.py                  # -> data/external/sisfall_sessions/ (~4.500 phiên)
python train_rf.py --experiment A1 --no-baro --data "data/raw,data/external/sisfall_sessions"
```

`import_sisfall.py` (`har_ml/sisfall.py`): gia tốc MMA8451Q (±8 g như MPU6050), con quay ITG3200 cắt ±500 °/s; lọc + lấy mẫu 200 → 50 Hz; mỗi người xoay để trọng lực khi đi bộ (D01) trùng `UPRIGHT` (X chỉ xuống). Nhãn: D01, D02 → `walk`; F01–F15 → `fall` (chỉ đoạn quanh đỉnh lớn nhất, `fall_lie: false`); hoạt động khác → `adl` (không dùng huấn luyện, để đo báo động giả). Không có áp suất: thí nghiệm có BMP280 chỉ dùng dữ liệu tự thu. Hướng quanh trục đứng (trước/sau) không căn được. `data/external/` nằm trong `.gitignore`.

**Đánh giá khi có SisFall** (`har_ml/evaluate.py: subject_splits`): leave-one-subject-out **chỉ trên người tự thu** (S01…). Mỗi lượt để riêng một người tự thu làm tập kiểm tra, huấn luyện trên mọi người còn lại *cộng toàn bộ* SisFall; điểm số chỉ tính trên người tự thu, nên phản ánh người đeo bộ har01 thật. `eval_fall.py` cũng chỉ "phát lại" người tự thu. Để so sánh, chạy cùng thí nghiệm với `--data data/raw --out results_own`.

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

### Kết quả 2026-11-18 (S01–S04, leave-one-subject-out, macro-F1 7 lớp)

| Thí nghiệm | Chỉ tự thu | Tự thu + SisFall |
| --- | --- | --- |
| A1 RF chỉ IMU | 0,715 | 0,822 |
| A2 RF IMU + BMP280 | 0,717 | **0,910** |
| B1 CNN chỉ IMU | 0,717 | 0,881 |
| B2 CNN IMU + BMP280 | 0,697 | 0,904 |
| C RF IMU + BMP280, cửa sổ 2,0 s | 0,734 | 0,909 |

**Xoay tín hiệu về hướng đứng (từ 19/11, mặc định):** `extract_features(..., align=True)` xoay gia tốc và con quay sao cho hướng đứng đã hiệu chỉnh trùng X chỉ xuống, trước khi tính đặc trưng. Đặc trưng theo từng trục khi đó không phụ thuộc người đeo nghiêng hộp bao nhiêu. Model ghi `"align_upright": true` trong `meta.json`; `--no-align` để chạy cách cũ.

| Thí nghiệm (tự thu + SisFall) | Trục chip | Xoay về hướng đứng |
| --- | --- | --- |
| A1 RF chỉ IMU | 0,822 | 0,885 |
| A2 RF IMU + BMP280 | 0,910 | **0,929** |
| C RF IMU + BMP280, 2,0 s | 0,909 | 0,937 |

Lý do: thử trực tiếp 19/11, người đeo đứng 2 phút nhưng model cũ đoán "lên cầu thang" 72 % thời gian (hộp nghiêng 26° so với X). Model xoay: 67 % đứng. Thêm bộ chặn của `har-infer` (bỏ nhãn cầu thang khi |Δcao 10 s| < 0,3 m; đứng/đi 0,09–0,11 m, cầu thang 1,5–1,7 m): còn 1 % cầu thang. Luồng 1 s trên phiên tự thu: đứng đúng 0,75 → 0,97, lên cầu thang 0,80 → 0,75.

**Đặc trưng thẳng đứng + nằm ngang (từ 20/11, mặc định, model v3):** `extract_features(..., yaw_invariant=True)` tách tín hiệu đã xoay thành thành phần thẳng đứng và độ lớn nằm ngang, nên không phụ thuộc hộp quay quanh trục đứng (đeo hông, bụng…). `--axis-features` để dùng bộ theo trục (v2). Chấm trên dữ liệu thử T01 ở 4 vị trí đeo (`ml/data/test/`, không huấn luyện): v1 82 %, v2 88 %, **v3 92 %**; trên S01–S04 v3 ≈ v2 (A2 0,928). Chi tiết: `docs/firmware-integration.md` mục 22.

**Model v4 (20/11):** như v3, học thêm dữ liệu S01 ở 4 vị trí đeo khác (E–H, `note` có `train`). Trên các phiên gốc S01–S04: macro-F1 0,927 → 0,963 (đứng 0,79 → 0,97). T01 không bộ chặn: 87 % → 95 %. Macro-F1 LOSO in ra bởi `train_rf.py` giảm (A2 0,889) vì tập chấm của S01 giờ có cả vị trí E–H mà người khác chưa có, chứ không phải model kém đi. Chi tiết: `docs/firmware-integration.md` mục 23.

Chỉ S01 thu té, nên khi để riêng S01 làm tập kiểm tra, cột "chỉ tự thu" không có cú té nào để học (F1 té = 0). Với SisFall, F1 té trên S01 là 0,99–1,00 (RF) và 0,91 (CNN). Chỉ có 4 người nên số liệu còn dao động. Với RF, siêu tham số được chọn trên chính các dự đoán out-of-fold, nên kết quả hơi lạc quan.

### Kết quả trong repo

Mô tả dataset, số phiên theo người và hoạt động, link Google Drive: [`data/README.md`](data/README.md). Các file `metrics.json` của dữ liệu thật được commit (số liệu cho báo cáo); mỗi file ghi tên model, ngày chạy và các tùy chọn đặc trưng (`extra`):

| Thí nghiệm | `results/`: tự thu + SisFall | `results_own/`: chỉ tự thu |
| --- | --- | --- |
| A1 RF chỉ IMU | 0,833 (20/11) | 0,715 (18/11) |
| A2 RF IMU + BMP280 | **0,889** (20/11, model v4 đang chạy trên Pi) | 0,717 (18/11) |
| B1 CNN chỉ IMU | 0,881 (18/11) | 0,717 (18/11) |
| B2 CNN IMU + BMP280 | 0,904 (18/11) | 0,697 (18/11) |
| C RF IMU + BMP280, 2,0 s | 0,881 (20/11) | 0,734 (18/11) |
| D phát hiện té, S01 | Ngưỡng 18/23, model 23/23, kết hợp 23/23 (20/11) | Ngưỡng 18/23, model 0/23: không có té để học (18/11) |

Số là macro-F1 LOSO in ra bởi script. Bản 20/11 dùng đặc trưng xoay về hướng đứng + thẳng đứng/nằm ngang và học thêm S01 ở vị trí E–H, nên tập chấm của S01 khó hơn bảng 18/11 ở trên (xem đoạn "Model v4"). B1, B2 (CNN) chưa chạy lại với đặc trưng mới. Trang Đánh giá model trên dashboard đang hiện A1, A2, C, D của `results/`.

Mỗi thí nghiệm ghi `results/<thí nghiệm>/metrics.json` (accuracy, macro-F1, F1 từng lớp, ma trận nhầm lẫn, số cửa sổ, số người, phiên bản model). Đẩy lên cloud để trang **Đánh giá model** hiển thị:

```bash
python push_metrics.py                       # đọc VPS_API_URL, VPS_DEVICE_KEY từ edge/.env (URL Worker Cloudflare)
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
