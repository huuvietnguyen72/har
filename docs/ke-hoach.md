# Kế hoạch dự án HAR

Cập nhật 21/11/2026, theo hệ thống đang chạy thật. Cấu trúc hệ thống: [`kien-truc.md`](kien-truc.md), phần cứng (sơ đồ mạch, hộp): [`hardware/README.md`](../hardware/README.md), bảng chân: [`pinout.md`](pinout.md), nhật ký tích hợp (24 mục, mọi vấn đề và cách sửa): [`firmware-integration.md`](firmware-integration.md), vận hành hằng ngày: [`van-hanh.md`](van-hanh.md).

## Mục tiêu

- Bộ đeo hông nhận dạng 7 hoạt động ([`labels.md`](labels.md)) và phát hiện té ngã cho người cao tuổi, prototype giám sát trong nhà.
- IoT Level 5, 3 tầng: bộ đeo ESP32 → Raspberry Pi 4 (edge, chạy model) → cloud (Cloudflare: lưu trữ, dashboard). Mọi số liệu đánh giá xem được trên cloud.
- Cảnh báo té: còi trên bộ đeo (người đeo có 10 s tự hủy), Telegram, dashboard.

## Hệ thống hiện có

| Phần | Trạng thái |
| --- | --- |
| Bộ đeo `har01` | ESP32-D0WD-V3; một bus I2C GPIO21/22: MPU6050 (0x68), AHT20 + BMP280 (0x38 + 0x77), OLED (0x3C); nút GPIO19; loa GPIO25; LED xanh GPIO26, đỏ GPIO27. Pin LiPo 1000 mAh → TP4056 → công tắc → MT3608 5 V, không đo áp pin. Hộp in 3D 95 × 60 × 40 mm, kẹp thắt lưng hông phải. Firmware 1.0.0, 50 Hz. Nút: 1 lần bật màn hình, đúp `marker`, **3 lần hiệu chỉnh hướng đứng**, giữ 3 s SOS |
| Mạng | ESP32 và Pi cùng Wi-Fi nhà (2,4 GHz), dải 192.168.12.0/24. Pi `raspivn` (192.168.12.19) |
| Pi 4 | Mosquitto, chrony, `har-ingest`, `har-infer`, `har-uplink`, `har-notify`, `har-bot` (systemd) |
| Model | **v4**: Random Forest, IMU + BMP280, cửa sổ 2,5 s, xoay tín hiệu về hướng đứng + đặc trưng thẳng đứng/nằm ngang; học trên S01–S04 + SisFall. Bộ chặn cầu thang khi độ cao không đổi (0,3 m/10 s) |
| Cloud | **Cloudflare Worker + D1** ([`cloud/`](../cloud/)): API + dashboard 4 trang tại `https://har-cloud.har-cloud.workers.dev`, cập nhật mỗi 2 s, hộp cảnh báo té giữa màn hình. Bản VPS (`backend/`) giữ làm dự phòng |
| Telegram | `har-notify` gửi cảnh báo; `har-bot` nhận lệnh `/trangthai`, `/homnay`, `/coi`, `/tatcoi`, `/hieuchinh`, `/thu`, `/dung` |
| Dataset | S01–S04 (đứng, ngồi, nằm, đi, lên/xuống cầu thang; té chỉ S01: 23 cú) + S01 ở 4 vị trí đeo lạ (E–H) + SisFall (1.798 cú té, 38 người) cho huấn luyện. T01: 41 phiên ở 4 vị trí đeo (A–D), chỉ để chấm điểm |

## Đã đo trên hệ thống thật

| Phép thử | Kết quả |
| --- | --- |
| Truyền liên tục 30 phút | 50,000 Hz, mất 0 gói |
| Chặn mạng ESP32 30 s | Gửi bù 87 gói `replay`, mất 4 gói (~2 s), không reset |
| Mất gói theo ngày (16–20/11) | 0–0,12 % |
| Độ trễ bộ đeo → Pi | Trung vị 18 ms, p95 28 ms |
| Mẫu cuối → kết quả trên Pi | Trung vị 71 ms, p95 139 ms; suy luận RF trên Pi ~28 ms/cửa sổ |
| Pi → cloud | Trung vị 0,6 s, chậm nhất 1,9 s (sau khi giữ kết nối HTTP 60 s) |
| Đổi hoạt động → dashboard đổi | ~2 s sau khi Pi gửi (thêm 2–3 s model xác định tư thế mới) |
| Macro-F1 (LOSO, S01–S04, phiên gốc) | v1 0,910 → v4 **0,963** (đứng 0,79 → 0,97) |
| Dữ liệu thử T01, 4 vị trí đeo | v1 82 %, v2 88 %, v3 92 %, **v4 95 %** (đứng 25 % → 99 %) |
| Phát hiện té, S01 (thí nghiệm D) | Ngưỡng bộ đeo 18/23, model 23/23, kết hợp **23/23** |
| Báo giả trên ADL SisFall | 21/2.626 phiên (0,8 %); ADL tự thu: 0 |
| Té chỉ model thấy (21/11) | Còi kêu ~8 s sau té, người đeo hủy được; không hủy → Telegram ~19 s sau té |
| Hiệu chỉnh hướng đứng (nút / `/hieuchinh`) | Kết quả sau ~2 s |

## Việc tiếp theo

### 1. Đo thực tế (≥ 2 giờ, chạy bằng pin)

- [ ] Rút USB, đeo sinh hoạt bình thường ≥ 2 giờ; `uptime_s` tăng liên tục, không reset.
- [ ] Báo động giả mỗi giờ khi sinh hoạt thật (mục tiêu ≤ 0,5/giờ).
- [ ] Thời lượng pin: sạc đầy, chạy tới khi tắt (mạch không đo áp pin, đo bằng thời gian tới `online: false`).
- [ ] CPU Pi < 50 %, bộ nhớ không tăng dần sau 2 giờ.

### 2. Pi và mạng

- [x] Sửa DNS trên Pi (21/11): kết nối "BIGHOME 02" dùng `192.168.12.1`, `1.1.1.1`, bỏ `192.168.102.1` do router cấp; phân giải tên 5,03 s → 0,01 s ([`van-hanh.md`](van-hanh.md#dns-chậm)).
- [x] Gỡ trang tạm 8080 trên Pi, đóng cổng tường lửa (21/11): đã có dashboard cloud.
- [ ] Tùy chọn: bật lưu nhật ký qua các lần khởi động (`/var/log/journal`). Nhật ký đang nằm trong RAM, nên sau khi Pi tắt (dù `sudo poweroff` hay mất điện) không xem lại được.
- [ ] Đặt IP cố định cho Pi trên router (mDNS `raspivn.local` thỉnh thoảng không trả lời).
- [x] Pi tắt bằng `sudo poweroff` rồi bật lại (21/11): 7 dịch vụ tự chạy, đồng hồ tự đồng bộ, bộ đeo bật sau tự nối lại.

### 3. Bộ đeo

- [ ] Đo dòng tiêu thụ bằng USB tester.
- [x] Sơ đồ lắp mạch và cấu trúc hộp theo mạch thật ([`hardware/`](../hardware/README.md), 21/11).
- [ ] Ghi mã linh kiện chưa đối chiếu (transistor loa, điện trở LED và chân B).
- [ ] Tùy chọn: hiệu chỉnh gia tốc kế 6 mặt (SVM nằm yên 0,942 g).

### 4. Model (tùy chọn)

- [ ] Thêm người đeo ở vị trí lạ (T01 và S01 cùng một người; muốn chắc cho người khác cần người thứ hai).
- [ ] Huấn luyện lại 1D-CNN (B1/B2) với bộ đặc trưng v4 rồi đẩy kết quả lên trang Đánh giá model.

### 5. Demo

| Chỉ số | Cách đo | Mục tiêu | Hiện có |
| --- | --- | --- | --- |
| Macro-F1 | LOSO theo người | ≥ 0,85 | 0,963 (phiên gốc) |
| Độ nhạy té | Người không dùng để huấn luyện | ≥ 95 % | 23/23 (S01, model học SisFall) |
| Báo động giả | Đeo sinh hoạt ≥ 2 giờ | ≤ 0,5/giờ | Chưa đo (mục 1) |
| Độ trễ bộ đeo → Pi | Giờ nhận so với giờ mẫu | Trung vị < 100 ms | 18 ms |
| Độ trễ Pi → web app | Giờ ghi trên cloud so với giờ gửi | p95 < 2 s | Tối đa 1,9 s |
| Va chạm → Telegram | Quay video đồng hồ và điện thoại | < 15 s kể cả 10 s chờ hủy | ~13 s (bộ đeo tự phát hiện), ~19 s (chỉ model) |
| Mất gói MQTT | Đếm lỗ hổng `seq` | < 1 % | ≤ 0,12 % |
| Thời lượng pin | Chạy đến khi tắt | Ghi số thật | Chưa đo (mục 1) |

- [ ] Chạy thử toàn bộ kịch bản ở phòng demo trước một tuần; quay video dự phòng.
- [ ] Pin sạc đầy, mang cáp USB, nệm té; Pi có Internet (không có RTC, cần Internet để có giờ đúng).
- [ ] Tài khoản dashboard cho giảng viên (`node cloud/scripts/admin.mjs create-user ... --remote`); giảng viên vào nhóm Telegram.
- [ ] Mở dashboard bằng 4G trên máy chiếu để chứng minh là cloud.

Kịch bản khoảng 5 phút: giới thiệu bộ đeo và kiến trúc → đứng, ngồi, đi, nằm, dashboard đổi theo → té lên nệm, nhấn hủy, không có Telegram → té lần hai không hủy: còi kêu, Telegram tới, hộp đỏ giữa dashboard, bấm "Đã xử lý" → `/trangthai`, `/homnay` trên Telegram → trang Đánh giá model → clip cầu thang quay sẵn.

### 6. Báo cáo

Theo 10 bước thiết kế hệ thống IoT của Bahga & Madisetti. Bước 9 lấy từ datasheet và bảng chân; bước 10 từ firmware, edge, model, cloud; phần kết quả từ bảng "Đã đo" ở trên và [`firmware-integration.md`](firmware-integration.md). Trích dẫn SisFall (Sucerquia và cộng sự, Sensors 2017).

## Rủi ro

| Rủi ro | Cách xử lý |
| --- | --- |
| Không đo được áp pin, không có cảnh báo pin yếu | Biết thời lượng pin đã đo; sạc đầy trước demo |
| Pi tắt (`poweroff`, mất điện) hoặc mất mạng | Cloud nhắn Telegram "Pi mất kết nối" sau 10 phút và khi Pi lên lại; bộ đeo vẫn tự kêu còi khi té nhưng không có Telegram về té, dashboard và model cho tới khi Pi chạy lại |
| Pi không có RTC, mDNS không ổn định | Internet cho Pi khi demo; IP cố định |
| Telegram lỗi phía máy chủ (20/11: 502 trong 19 phút) | Bot tự kết nối lại; dashboard và còi bộ đeo vẫn chạy |
| Gói miễn phí Cloudflare giới hạn request/ngày, CPU 10 ms/request | Dashboard ngừng hỏi khi tab ẩn; theo dõi mức dùng trên dashboard Cloudflare |
| Model mới chỉ chắc với người đeo đã gặp | Hiệu chỉnh hướng đứng khi đổi người/cách đeo; ghi rõ hạn chế trong báo cáo |
| Té mô phỏng gây chấn thương | Nệm dày, té từ tư thế quỳ, có người đỡ |
| Lộ mật khẩu Wi-Fi, MQTT, token Telegram, khóa thiết bị | `secrets.h`, `.env` trong `.gitignore`; log che token; token Telegram đã đổi sau sự cố 19/11 |
