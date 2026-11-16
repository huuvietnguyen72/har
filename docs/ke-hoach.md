# Kế hoạch dự án HAR

Cập nhật 17/11/2026, dựa trên hệ thống đang chạy thật. Phần cứng: [`hardware/Datasheet_HAR01.html`](../hardware/Datasheet_HAR01.html), bảng chân: [`pinout.md`](pinout.md), nhật ký tích hợp: [`firmware-integration.md`](firmware-integration.md).

## Mục tiêu

- Bộ đeo hông nhận dạng 8 hoạt động ([`labels.md`](labels.md)) và phát hiện té ngã cho người cao tuổi, prototype giám sát trong nhà.
- IoT Level 5, 3 tầng: bộ đeo ESP32 → Raspberry Pi 4 (edge, chạy model) → VPS (lưu trữ, dashboard). Mọi số liệu đánh giá xem được trên cloud.
- Cảnh báo té qua Telegram và web app.

## Hệ thống hiện có

| Phần | Trạng thái |
| --- | --- |
| Bộ đeo `har01` | ESP32-D0WD-V3; một bus I2C GPIO21/22 với MPU6050 (0x68), AHT20 + BMP280 (0x38 + 0x77), OLED (0x3C); nút GPIO19; loa GPIO25 qua transistor; LED xanh GPIO26, đỏ GPIO27. Pin Li-ion qua mạch sạc và tăng áp 5 V, không đo áp pin. Đeo hông phải, trục X chỉ xuống khi đứng. Firmware 1.0.0 chạy ổn định 50 Hz |
| Mạng | ESP32 và Pi cùng vào Wi-Fi nhà (2,4 GHz cho ESP32), dải 192.168.12.0/24. Pi `raspivn` (192.168.12.19), ESP32 tìm Pi qua `raspivn.local` |
| Pi 4 | Mosquitto (user/mật khẩu), chrony (máy chủ giờ), `har-ingest`, `har-infer`, `har-uplink`, `har-notify` chạy bằng systemd. Cài tay theo `edge/deploy/setup-pi.sh`, bỏ phần hotspot |
| Model | Code RF, 1D-CNN và các thí nghiệm A–D đã chạy trên dữ liệu giả lập. Chưa có dataset thật (mới có 1 phiên đi bộ thử) |
| Cloud | Backend FastAPI + PostgreSQL + Caddy và web app React 4 trang đã viết, có test. Chưa thuê VPS; Pi đang đẩy ra màn hình (`CLOUD_BACKEND=console`) |
| Telegram | `har-notify` đã viết, chưa kiểm chứng với bot thật |

## Đã đo trên hệ thống thật

| Phép thử | Kết quả |
| --- | --- |
| Truyền liên tục 30 phút | 50,000 Hz, mất 0 gói |
| Chặn mạng ESP32 30 s | Gửi bù 87 gói `replay`, mất 4 gói (~2 s), không reset |
| Thả hộp lên nệm, nhấn nút trong 10 s | `suspected` (va chạm 8,5 g và 12,1 g) rồi `cancelled` |
| Giữ nút 3 s | `sos` tới Pi trong 0,3 s |
| Lệch giờ ESP32 so với Pi | Trung vị −20 ms |
| Hiệu chỉnh con quay khi khởi động | Lệch nằm yên còn −0,03 / −0,02 / −0,01 °/s |
| Hiệu chỉnh hướng đứng thẳng | Kết quả sau 2,1 s; phiên đi bộ: luật nhận dạng đúng 58/58 cửa sổ |

## Việc tiếp theo

### 1. Bộ đeo

- [ ] Rút USB, chạy bằng pin: theo dõi `har/har01/status` trên Pi, `uptime_s` phải tăng liên tục, không reset.
- [ ] Đo thời lượng pin: sạc đầy, chạy liên tục đến khi tắt; lấy mốc `online: false` trên Pi (mạch không đo áp pin nên đo bằng thời gian).
- [ ] Đo dòng tiêu thụ bằng USB tester.
- [ ] Ghi mã các linh kiện chưa đối chiếu (transistor loa, điện trở LED, module sạc và tăng áp), chụp ảnh mạch và hộp, cập nhật datasheet.
- [ ] Tùy chọn: hiệu chỉnh gia tốc kế 6 mặt (SVM nằm yên đang là 0,942 g).

### 2. Pi và mạng

- [ ] Đặt IP cố định cho Pi trên router, ghi IP vào `MQTT_HOST` (mDNS thỉnh thoảng không trả lời).
- [ ] Khởi động lại Pi, xác nhận ESP32 tự nối lại trong 30 s và dịch vụ tự chạy.
- [ ] Thêm chế độ mạng nhà cho `setup-pi.sh` (script hiện chỉ dựng hotspot), để cài lại Pi không phải làm tay.
- [ ] Tùy chọn: hạ keepalive MQTT để giảm số gói mất khi rớt mạng.

### 3. Thu dataset

- Ít nhất 5 người, mã ẩn danh S01, S02…; ghi tuổi, chiều cao, cân nặng.
- Đeo hông phải, cùng hộp, cùng đai. Trước mỗi người, `record.py` tự gửi `calibrate_upright` (người đeo đứng thẳng yên ~2 s).
- Mỗi phiên một hoạt động: `record.py --subject S01 --activity walk`. Nhấn đúp nút tạo `marker` để đồng bộ với video điện thoại.
- Gửi `calibrate_gyro` hoặc khởi động lại bộ đeo lúc nằm yên trước phiên dài, vì độ lệch con quay đổi theo nhiệt độ.

| Nhãn | Cách thu | Mỗi người |
| --- | --- | --- |
| Đứng | Đứng yên, làm việc nhẹ | 3 phút |
| Ngồi | Ghế cứng, ghế mềm, ngồi bệt | 3 phút |
| Nằm | Ngửa, nghiêng trái, nghiêng phải | 3 phút |
| Đi | Bình thường, chậm | 3 phút |
| Chạy | Chạy bộ nhẹ | 2 phút |
| Lên cầu thang | Cùng một cầu thang ≥ 2 tầng | 10 lượt |
| Xuống cầu thang | Như trên | 10 lượt |
| Té | Trước, sau, nghiêng trái, nghiêng phải lên nệm dày | 4 hướng × 5 lần |

Thu thêm động tác dễ nhầm (ngồi phịch xuống ghế, nhảy, cúi nhặt đồ, nằm xuống nhanh) để đo báo động giả.

**An toàn khi thu té:** chỉ người trẻ, khỏe; té từ tư thế quỳ hoặc đứng lên nệm ≥ 10 cm; có người đứng cạnh; hộp không đè trực tiếp lên hông khi ngã.

### 4. Huấn luyện model

- Chép `edge/data/sessions/` từ Pi về `ml/data/raw/`; làm sạch và cắt cửa sổ theo [`ml/README.md`](../ml/README.md).
- Chia tập theo người (GroupKFold), không chia ngẫu nhiên theo cửa sổ.
- Chạy thí nghiệm A1/A2 (RF chỉ IMU / thêm BMP280), B1/B2 (1D-CNN), C (cửa sổ 2,0 s vs 2,5 s), D (ngưỡng ESP32 vs model vs kết hợp).
- Đẩy `metrics.json` lên cloud, chép model tốt nhất sang `edge/models/current/`.
- AHT20 bị ESP32 hâm nóng (43 °C sau 1 giờ): không dùng nhiệt độ, độ ẩm làm đặc trưng.

### 5. Suy luận và cảnh báo

- [ ] `har-infer` chạy model thật thay cho luật đơn giản.
- [ ] Tạo bot Telegram, thêm vào nhóm người thân, điền `TELEGRAM_*` trong `.env` trên Pi.
- [ ] Độ trễ từ mẫu cuối đến kết quả trên Pi < 200 ms (trung vị và p95).
- [ ] Té trên nệm → Telegram đến trong < 5 s sau khi hết 10 s chờ hủy; nhấn hủy → không có tin.
- [ ] CPU Pi < 50 %, chạy liên tục 2 giờ không rò bộ nhớ.

### 6. Cloud

- [ ] Thuê VPS, trỏ tên miền, dựng theo [`backend/DEPLOY.md`](../backend/DEPLOY.md).
- [ ] Pi đổi sang `CLOUD_BACKEND=vps`, outbox xả hết sau khi mất Internet.
- [ ] URL HTTPS mở được bằng 4G; gọi API không có JWT hoặc API key → 401.
- [ ] Trang Tổng quan cập nhật ≤ 10 s sau khi người đeo đổi hoạt động.
- [ ] Khởi động lại VPS không mất dữ liệu; khôi phục được DB từ bản sao lưu.

### 7. Đánh giá và demo

| Chỉ số | Cách đo | Mục tiêu |
| --- | --- | --- |
| Macro-F1 | GroupKFold theo người | ≥ 0,85 |
| F1 cầu thang | Có / không BMP280 | Tăng rõ khi có BMP280 |
| Độ nhạy té | Phiên té của người không dùng để huấn luyện | ≥ 95 % |
| Báo động giả | Đeo sinh hoạt ≥ 2 giờ | ≤ 0,5 / giờ |
| Độ trễ bộ đeo → Pi | Giờ nhận trên Pi so với giờ mẫu | Trung vị < 100 ms |
| Độ trễ Pi → web app | Giờ ghi trên cloud so với giờ gửi | p95 < 2 s |
| Va chạm → Telegram | Quay video đồng hồ và điện thoại | < 15 s, kể cả 10 s chờ hủy |
| Mất gói MQTT | Đếm lỗ hổng `seq` | < 1 % |
| Thời lượng pin | Chạy đến khi tắt (mục 1) | Ghi số thật |

Chuẩn bị demo:

- [ ] Chạy thử toàn bộ kịch bản ở phòng demo một tuần trước; quay video dự phòng.
- [ ] Pin sạc đầy (không có cảnh báo pin yếu), mang cáp USB, nệm té.
- [ ] Pi có Internet (Pi không có RTC, cần Internet để có giờ đúng): mạng nhà hoặc chia sẻ từ điện thoại.
- [ ] Tài khoản web app cho giảng viên; giảng viên trong nhóm Telegram.
- [ ] Mở web app trên máy chiếu bằng mạng khác với Pi để chứng minh là cloud.

Kịch bản khoảng 5 phút: giới thiệu bộ đeo và kiến trúc → đứng, ngồi, đi, nằm và xem trang Tổng quan đổi theo → té lên nệm, nhấn hủy, không có Telegram → té lần hai không hủy, loa kêu, Telegram đến → rút Internet của Pi rồi cắm lại, lịch sử được bù → trang Đánh giá model → clip cầu thang quay sẵn.

### 8. Báo cáo

Theo 10 bước thiết kế hệ thống IoT của Bahga & Madisetti. Bước 9 (Device & Component Integration) lấy từ datasheet và bảng chân; bước 10 lấy từ firmware, edge, model và web app; phần kết quả lấy từ bảng chỉ số ở mục 7.

## Rủi ro

| Rủi ro | Cách xử lý |
| --- | --- |
| Không đo được áp pin, không có cảnh báo pin yếu | Biết thời lượng pin đã đo; sạc đầy trước demo |
| OLED chung bus I2C, thời điểm đọc MPU6050 lệch tới ~3 ms khi màn vẽ | Firmware gửi màn từng dải 8 dòng; theo dõi `lỡ=` trong `[stat]` |
| Pi không có RTC, mDNS không ổn định | Internet cho Pi khi demo; IP cố định |
| Dataset ít người, model học thuộc | Chia theo người, đủ 5 người, báo cáo số thật |
| Té mô phỏng gây chấn thương | Nệm dày, té từ tư thế quỳ, có người đỡ |
| VPS lỗi đúng lúc demo | Giám sát `/api/health`, sao lưu DB hằng ngày, video dự phòng |
| Lộ mật khẩu Wi-Fi, MQTT, token Telegram, API key | `secrets.h`, `.env` nằm trong `.gitignore`; repo riêng tư |
