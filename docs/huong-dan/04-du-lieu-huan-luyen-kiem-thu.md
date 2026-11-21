# 4. Thu dữ liệu, huấn luyện và kiểm thử

Quy trình: thu phiên có nhãn trên bộ đeo + Pi → chép sang laptop → huấn luyện ở `ml/` → đánh giá → đưa model lên Pi → đẩy kết quả lên dashboard. Chi tiết kỹ thuật: [`../../ml/README.md`](../../ml/README.md). Dataset hiện có: [`../../ml/data/README.md`](../../ml/data/README.md).

## 4.1. Cài môi trường trên laptop

```bash
cd ml
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -e ../edge -r requirements.txt
```

`ml/` dùng chung file đặc trưng `edge/har_edge/features.py` với Pi, nên đặc trưng lúc huấn luyện và lúc chạy thật không thể lệch nhau. Windows: đặt `PYTHONIOENCODING=utf-8` trước khi chạy script in tiếng Việt (xem sự cố).

## 4.2. Thu dữ liệu

### Chuẩn bị

- Bộ đeo đã nối Pi (bước 2, 3). Bật bộ đeo, đặt yên ~2 s để con quay tự hiệu chỉnh.
- Kẹp đúng vị trí, **hiệu chỉnh hướng đứng** cho mỗi người: nhấn nút 3 lần rồi đứng thẳng yên (bíp dài = đạt), hoặc `/hieuchinh`.
- Mã người đeo là bí danh: `S01`, `S02`… cho dữ liệu huấn luyện, `T01`… cho dữ liệu chỉ để chấm điểm. Không ghi tên thật.
- Té: **chỉ té lên nệm dày**, từ tư thế quỳ hoặc đứng, có người đỡ.

### Cách 1: Telegram (tiện nhất khi thu nhiều lượt)

```
/thu S01 walk                     # bắt đầu; nút Dừng / Lượt nữa
/thu T01 stairs_up vitri=A        # ghi chú sau nhãn (vị trí đeo, ghi chú khác)
/dung                             # dừng
```

Nút **Đổi chiều** đổi giữa lên ↔ xuống cầu thang. Phiên tự dừng sau 10 phút.

### Cách 2: trên Pi

```bash
cd ~/har/edge
.venv/bin/python record.py --subject S01 --activity walk --duration 60 --note "vitri=E train"
```

Bỏ `--no-upright-cal` thì `record.py` tự yêu cầu hiệu chỉnh hướng đứng trước khi đếm ngược. Nhãn hợp lệ: `stand`, `sit`, `lie`, `walk`, `stairs_up`, `stairs_down`, `fall` ([`../labels.md`](../labels.md)).

### Thời lượng nhóm đã dùng

| Hoạt động | Mỗi phiên |
| --- | --- |
| Đứng, ngồi, nằm, đi | 60–180 s |
| Lên / xuống cầu thang | Một lượt (dừng khi tới đầu/cuối cầu thang) |
| Té | ~12 s quanh cú té, 4 hướng (trước, sau, trái, phải) |

Trong lúc thu, còi **không kêu** khi té (màn hình `REC`), chỉ LED đỏ + OLED, để còi không làm nhiễu gia tốc kế. Hết phiên `record.py` tự hủy cảnh báo.

### Kiểm tra và dọn phiên lỗi

Sau mỗi buổi, xem từng phiên (thời lượng, số mẫu, áp suất có đổi ở phiên cầu thang không) và xóa phiên lỗi **trên cả Pi và laptop**: dừng sớm vài giây, đứng yên trong phiên cầu thang, lẫn lên và xuống, thu nhầm nhãn. Nhầm nhãn vị trí trong ghi chú thì sửa `note` trong `meta.json`.

### Chép về laptop và Drive

```bash
scp -r pi@192.168.12.19:har/edge/data/sessions/* ml/data/raw/       # dữ liệu huấn luyện (S..)
# phiên T.. chép vào ml/data/test/sessions/, KHÔNG vào raw/
```

Chỉ chép `data/sessions/`, **không** chép `data/sessions_backup/`. Thu xong một đợt thì nén lại và thay file zip trên Google Drive ([`../../ml/data/README.md`](../../ml/data/README.md)).

## 4.3. Dataset ngoài: SisFall

Chỉ S01 thu té, nên model học thêm té từ SisFall (38 người, 1.798 cú té):

```bash
cd ml
git clone --depth 1 https://gitee.com/yuxiqin/imu-fall-database.git data/external/SisFall
python import_sisfall.py               # -> data/external/sisfall_sessions/ (~4.500 phiên)
```

Phải trích dẫn SisFall trong báo cáo (Sucerquia và cộng sự, Sensors 2017). Không commit SisFall.

## 4.4. Huấn luyện

```bash
cd ml
D="data/raw,data/external/sisfall_sessions"
python train_rf.py --experiment A2 --baro --data "$D" --export --version v5   # model chạy trên Pi (RF, IMU + áp suất)
python train_rf.py --experiment A1 --no-baro --data "$D"                       # so sánh: chỉ IMU
python train_rf.py --experiment C --baro --window 2.0 --data "$D"              # so sánh: cửa sổ 2,0 s
python train_cnn.py --experiment B2 --baro --data "$D"                         # 1D-CNN
python eval_fall.py --baro --data "$D"                                         # D: phát hiện té
python run_experiments.py --data "$D"                                          # chạy tất cả
```

- `--export` ghi `models/rf-imu+baro-2.5s-<version>/` (`meta.json` + `model.joblib`). Đặt `--version` mới mỗi lần để không ghi đè model đang chạy (hiện tại là `v4`).
- Mặc định đặc trưng đã **xoay về hướng đứng** và **tách thẳng đứng / nằm ngang** (không phụ thuộc cách đeo). `--no-align`, `--axis-features` chỉ để so sánh với cách cũ.
- Kết quả ghi `results/<thí nghiệm>/metrics.json`. Chạy cùng thí nghiệm chỉ trên dữ liệu tự thu: `--data data/raw --out results_own`.

## 4.5. Đánh giá

| Cách chấm | Ý nghĩa | Kết quả hiện tại |
| --- | --- | --- |
| **LOSO** (leave-one-subject-out): để riêng một người tự thu làm tập kiểm tra, học trên người còn lại + SisFall | Model có dùng được cho người chưa gặp không. **Không bao giờ chia ngẫu nhiên theo cửa sổ** (cửa sổ cùng phiên lọt sang tập kiểm tra, điểm ảo) | Macro-F1 v4 0,963 trên phiên gốc S01–S04 |
| **Dữ liệu thử T01** ở 4 vị trí đeo, không bao giờ huấn luyện | Đổi cách đeo có còn nhận đúng không | v4: 95 % (đứng 99 %) |
| **D: phát hiện té** (`eval_fall.py`): phát lại cú té S01 qua ngưỡng bộ đeo, model và quy tắc kết hợp; đo báo giả trên phiên sinh hoạt | Độ nhạy té, báo động giả | Ngưỡng 18/23, model 23/23, kết hợp 23/23; báo giả SisFall ADL 21/2.626 phiên |

Phép chấm T01 hiện chạy bằng script tạm (dự đoán mỗi 1 s như `har-infer`, bỏ 2 s đầu/cuối, có bộ chặn cầu thang), **chưa có trong repo**. Ai làm tiếp nên thêm thành `ml/eval_test.py`.

## 4.6. Đưa model lên Pi

```bash
# giữ bản cũ để quay lại được
ssh pi@192.168.12.19 'cd ~/har/edge/models && cp -a current rf-imu+baro-2.5s-v4-backup'
scp ml/models/rf-imu+baro-2.5s-v5/meta.json ml/models/rf-imu+baro-2.5s-v5/model.joblib pi@192.168.12.19:har/edge/models/current/
ssh pi@192.168.12.19 'sudo systemctl restart har-infer && journalctl -u har-infer -n 20 --no-pager'
```

Quay lại model cũ: [`../van-hanh.md`](../van-hanh.md#model-trên-pi). Sau khi đổi model, thử trực tiếp: đứng, ngồi, đi, nằm, cầu thang, té lên nệm; xem dashboard và `/trangthai`.

## 4.7. Đẩy kết quả lên dashboard

```bash
cd ml
python push_metrics.py        # đọc VPS_API_URL, VPS_DEVICE_KEY trong edge/.env
```

Khóa thiết bị chỉ nằm trên Pi; nếu laptop không có `edge/.env` thật thì chép `metrics.json` lên Pi và chạy ở đó. Kết quả từ dữ liệu giả lập (`"synthetic": true`) bị từ chối. Commit `metrics.json` mới vào repo (số liệu cho báo cáo).

## 4.8. Các bộ test

| Phần | Lệnh | Hiện tại |
| --- | --- | --- |
| Firmware (logic C++) | `cd firmware && pio test -e native` | 21 test |
| Edge (Pi) | `cd edge && pip install -e ".[dev]" && pytest -q` | 45 test |
| ML | `cd ml && pytest -q` | Chạy trên dữ liệu giả lập |
| Cloud đầu-cuối | Xem [bước 5](05-deploy-cloudflare.md#56-chạy-thử-trên-máy) | 10 test |
| Toàn tuyến không cần phần cứng | `edge/fake_device.py --script "walk:20,sit:15,fall:8,lie:10"` với 4 dịch vụ chạy trên laptop | |
| Phát lại phiên thật | `python edge/replay.py data/sessions/<id> --speed 2` | |

Chạy đủ test của phần mình sửa trước khi mở PR. Thử code ML khi chưa có dữ liệu: `python make_synthetic.py` (điểm gần 1,0, **vô nghĩa**, chỉ kiểm tra code chạy).

## Sự cố đã gặp

| Sự cố | Nguyên nhân | Xử lý |
| --- | --- | --- |
| Đoạn nằm sau té có dao động giả 2 Hz | Còi báo té rung cả hộp | Khi thu, còi tắt (chỉ LED + OLED); xóa 9 phiên té có tiếng còi để thu lại ([mục 16](../firmware-integration.md#16-loa-báo-té-làm-rung-gia-tốc-kế)) |
| Phiên có mẫu đo trước lúc bắt đầu / thiếu mẫu cuối | Gói tới trễ (sóng yếu ở cầu thang) bị gán sai phiên | Gán theo thời điểm đo, chờ 90 s rồi mới đóng phiên ([mục 17](../firmware-integration.md#17-gói-tới-trễ-lọt-sang-phiên-sau)) |
| 9 cảnh báo té `confirmed` giả khi thu té | Lỗi thời gian trong máy trạng thái cảnh báo; người đeo không kịp hủy | `lib/alarm_fsm`; `record.py` tự gửi `cancel_alarm` khi hết phiên ([mục 18](../firmware-integration.md#18-máy-trạng-thái-cảnh-báo-té)) |
| Mỗi người cài hộp nghiêng khác nhau, model nhận sai | Hướng đứng cố định chỉ đúng khi cài chuẩn | Hiệu chỉnh hướng đứng cho từng người ([mục 14](../firmware-integration.md#14-hiệu-chỉnh-hướng-đứng-thẳng-theo-người-đeo), [20](../firmware-integration.md#20-hiệu-chỉnh-hướng-đứng-thẳng-bằng-nút-và-telegram)) |
| Model không bao giờ tự báo té | P(té) của cú té người chưa gặp chỉ 0,5–0,7, quy tắc đòi ≥ 0,8 | Hạ xuống 0,5 + không báo khi đang nằm (trở mình); 0,5 nằm sát bờ, con số 96 % lạc quan ([mục 19](../firmware-integration.md#19-model-đầu-tiên-trên-pi-và-quy-tắc-model-tự-báo-té)) |
| Đứng bị nhận thành "lên cầu thang" 72 % | Đặc trưng theo trục chip phụ thuộc độ nghiêng hộp; áp suất 2,5 s không đủ phân biệt | Xoay về hướng đứng + bộ chặn cầu thang khi độ cao 10 s đổi < 0,3 m ([mục 21](../firmware-integration.md#21-đứng-bị-nhận-thành-lên-cầu-thang-khi-đổi-cách-đeo)) |
| Đeo giữa bụng, đứng bị nhận thành ngồi | Hộp quay quanh trục đứng | Đặc trưng thẳng đứng + nằm ngang (v3) ([mục 22](../firmware-integration.md#22-thử-ở-4-vị-trí-đeo-và-đặc-trưng-không-phụ-thuộc-hướng-quay-quanh-trục-đứng)) |
| Vẫn nhầm đứng ở vị trí lạ khi không có bộ chặn | Model chỉ học một cách đeo | Thu thêm S01 ở 4 vị trí E–H (v4): T01 87 % → 95 % ([mục 23](../firmware-integration.md#23-thu-thêm-dữ-liệu-ở-vị-trí-đeo-khác-model-v4)) |
| Model thấy té nhưng còi không kêu | Chỉ bộ đeo bật còi | Pi gửi `test_alarm`, người đeo vẫn có 10 s hủy ([mục 24](../firmware-integration.md#24-model-phát-hiện-té-nhưng-còi-bộ-đeo-không-kêu)) |
| 1D-CNN sụp, macro-F1 0,13 | `validation_split` của Keras lấy 15 % **cuối** mảng trước khi xáo, mà mảng xếp theo người: dữ liệu tự thu rơi hết vào validation | Xáo có seed trước khi `fit` (`train_cnn.py`) |
| Script Python lỗi `UnicodeEncodeError: 'charmap'` trên Windows | Console Windows dùng cp1252, không in được tiếng Việt | `set PYTHONIOENCODING=utf-8` (PowerShell: `$env:PYTHONIOENCODING="utf-8"`) |
| Phiên cầu thang lỗi (dừng sớm, đứng yên, lẫn lên/xuống), ghi nhầm vị trí | Thao tác khi thu | Kiểm tra sau mỗi buổi, xóa phiên lỗi, sửa `note` |
| Điểm LOSO của v4 thấp hơn v3 (0,889 so với 0,93) | Tập chấm của S01 có thêm vị trí E–H mà người khác chưa có | Không phải model kém; so sánh trên cùng tập phiên gốc thì 0,927 → 0,963 |

**Hạn chế cần ghi trong báo cáo:**
- Chỉ 4 người tự thu, té chỉ của 1 người (S01); T01 và S01 là cùng một người, nên kết quả ở vị trí lạ chưa chứng minh được cho người khác.
- Báo động giả khi sinh hoạt thật (≥ 2 giờ đeo tự do) chưa đo.
- B1, B2 (CNN) chưa chạy lại với bộ đặc trưng mới.
