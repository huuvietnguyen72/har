# Dataset

Dữ liệu thô **không nằm trong repo** (`.gitignore`). Bản đầy đủ ở Google Drive của nhóm:

**https://drive.google.com/drive/folders/1Uf1RFXNZ9EDUjotQG3zLrP9KjUrTptzd?usp=sharing**

Trên Drive có 2 file nén, giữ nguyên cấu trúc thư mục, và bản sao file này:

| File | Nội dung | Dung lượng |
| --- | --- | --- |
| `har-dataset-raw.zip` | `raw/`: 160 phiên huấn luyện | 5,5 MB |
| `har-dataset-test.zip` | `test/`: 41 phiên thử T01 + 2 log áp suất liên tục (`test/raw/`) | 1,4 MB |

Tải về rồi giải nén ngay trong thư mục này (`ml/data/`), sau đó chạy lệnh huấn luyện trong [`../README.md`](../README.md):

```bash
cd ml/data
unzip har-dataset-raw.zip      # -> raw/
unzip har-dataset-test.zip     # -> test/
```

| Thư mục | Nội dung | Dùng để | Trong repo |
| --- | --- | --- | --- |
| `raw/` | 160 phiên tự thu, S01–S04 | Huấn luyện, đánh giá LOSO | Không (tải từ Drive) |
| `test/sessions/` | 41 phiên thử, T01 ở 4 vị trí đeo | **Chỉ chấm điểm, không bao giờ huấn luyện** | Không (tải từ Drive) |
| `external/SisFall/`, `external/sisfall_sessions/` | SisFall gốc và bản đã chuyển định dạng (4.500 phiên) | Huấn luyện thêm té, đi bộ; đo báo động giả | Không (tải từ nguồn gốc, xem dưới) |
| `synthetic/` | Dữ liệu giả lập (`make_synthetic.py`) | Chạy thử code khi chưa có dữ liệu | Không (tự sinh) |

## Dữ liệu tự thu

Thu bằng bộ đeo `har01` (MPU6050 50 Hz, BMP280 10 Hz), đeo hông phải, hộp kẹp thắt lưng ([`../../hardware/README.md`](../../hardware/README.md)). Mỗi phiên là một hoạt động, thu bằng `edge/record.py` hoặc lệnh `/thu` trên Telegram, từ 17/11 đến 20/11/2026. Mã người đeo (S01…, T01) là bí danh, không ghi tên thật.

### Huấn luyện: `raw/` (160 phiên, 92,5 phút)

| Người | Đứng | Ngồi | Nằm | Đi | Lên cầu thang | Xuống cầu thang | Té | Tổng |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S01 | 9 · 14,2 ph | 3 · 3,0 ph | 3 · 3,0 ph | 6 · 9,0 ph | 13 · 2,8 ph | 16 · 2,7 ph | 23 · 4,6 ph | 73 phiên |
| S02 | 1 · 3,0 ph | 3 · 3,0 ph | 3 · 3,0 ph | 2 · 3,0 ph | 10 · 3,9 ph | 10 · 3,3 ph | 0 | 29 phiên |
| S03 | 1 · 3,0 ph | 3 · 3,0 ph | 3 · 3,0 ph | 2 · 3,0 ph | 10 · 2,6 ph | 10 · 2,5 ph | 0 | 29 phiên |
| S04 | 1 · 3,0 ph | 3 · 3,0 ph | 3 · 3,0 ph | 2 · 3,0 ph | 10 · 2,6 ph | 10 · 2,4 ph | 0 | 29 phiên |

Ô ghi "số phiên · số phút". Mất gói: 10/11.186 (0,09 %).

- **Té chỉ có ở S01** (23 cú, té lên nệm). Người khác học té từ SisFall.
- 41 phiên của S01 thu ở **4 vị trí đeo khác** (`note` có `vitri=E`…`H`, 9–11 phiên mỗi vị trí) để model không phụ thuộc cách đeo (model v4). 32 phiên còn lại của S01 và toàn bộ S02–S04 thu ở vị trí chuẩn.

### Thử: `test/sessions/` (41 phiên, 20,9 phút)

| Người | Đứng | Ngồi | Nằm | Đi | Lên cầu thang | Xuống cầu thang |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | 4 · 4,0 ph | 4 · 4,0 ph | 4 · 4,0 ph | 4 · 4,0 ph | 12 · 2,6 ph | 13 · 2,4 ph |

4 vị trí đeo A–D, mỗi vị trí 10–11 phiên. Mất gói 3/2.540. T01 và S01 là cùng một người, nên dữ liệu thử này đo việc **đổi cách đeo**, chưa đo việc **đổi người**.

### Định dạng một phiên

Mỗi phiên là một thư mục `{dev}_{người}_{hoạt động}_{YYYYMMDD-HHMMSS}/`:

| File | Cột | Ghi chú |
| --- | --- | --- |
| `imu.csv` | `t, ax, ay, az, gx, gy, gz` | 50 Hz; `t` epoch ms UTC; gia tốc theo g, con quay theo °/s, **theo trục chip** (đứng thẳng: ax ≈ −1 g); con quay đã trừ độ lệch |
| `env.csv` | `t, p_pa` | Áp suất (Pa), 10 Hz |
| `events.csv` | `t, type, id` | Sự kiện của bộ đeo trong phiên (`suspected`, `cancelled`, `marker`…), thường trống |
| `meta.json` | | `subject`, `activity`, `note`, `start`, `end`, `orientation`, `upright` (hướng đứng đã hiệu chỉnh, vectơ g theo trục chip), `upright_source`, `packets`, `lost`, `samples` |

Nhãn hoạt động: [`../../docs/labels.md`](../../docs/labels.md). Phiên té chỉ dài ~12 s quanh cú té; phiên đứng, ngồi, nằm, đi dài 1–3 phút; phiên cầu thang là một lượt lên hoặc xuống.

## SisFall

Sucerquia, López, Vargas-Bonilla, *SisFall: A Fall and Movement Dataset*, Sensors 17(1):198, 2017, doi:[10.3390/s17010198](https://doi.org/10.3390/s17010198). **Phải trích dẫn trong báo cáo.** Không đưa vào repo; tải từ nguồn rồi chuyển định dạng:

```bash
git clone --depth 1 https://gitee.com/yuxiqin/imu-fall-database.git data/external/SisFall
python import_sisfall.py        # -> data/external/sisfall_sessions/
```

| | Người | Phiên |
| --- | --- | --- |
| Té (F01–F15) | SA01–SA23 (19–30 tuổi), SE06 | 1.798 |
| Hoạt động thường ngày (D01–D19) | 38 người, gồm SE01–SE15 (60–75 tuổi) | 2.702 |

D01, D02 (đi bộ) → `walk`; F01–F15 → `fall`; hoạt động khác → `adl`, không dùng huấn luyện, chỉ để đo báo động giả. Không có áp suất. Cách chuyển (lọc, 200 → 50 Hz, xoay về hướng đứng): [`../README.md`](../README.md#dataset-ngoài-sisfall).

## Quy tắc

- Phiên mới: thu xong thì nén lại `raw/` (hoặc `test/`) và thay file zip trên Drive, cập nhật bảng số phiên ở trên; không commit vào repo.
- Phiên lỗi (đeo sai, thu nhầm nhãn): xóa cả thư mục phiên ở máy và trên Drive.
- `test/` không bao giờ đưa vào huấn luyện, kể cả khi đổi model.
