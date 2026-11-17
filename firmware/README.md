# Firmware ESP32

PlatformIO + Arduino framework (espressif32 6.9.0). Chân: [`include/pins.h`](include/pins.h) / [`../docs/pinout.md`](../docs/pinout.md). Phần cứng: [`../hardware/Datasheet_HAR01.html`](../hardware/Datasheet_HAR01.html). Payload: [`../docs/mqtt.md`](../docs/mqtt.md).

## Bắt đầu

1. VS Code + extension PlatformIO, **mở thư mục `firmware/`** (không phải gốc repo).
2. Copy `include/secrets.example.h` thành `include/secrets.h`, điền SSID, mật khẩu Wi-Fi, MQTT (`secrets.h` nằm trong `.gitignore`).
3. `pio run -e esp32dev -t upload && pio device monitor`
4. Test logic trên máy tính (cần gcc): `pio test -e native`

## Cấu trúc

| File | Việc làm |
| --- | --- |
| `src/main.cpp` | Tạo hàng đợi, mutex, 5 task FreeRTOS; in thống kê Serial mỗi 10 s |
| `src/sensors.cpp` | **samplerTask** (core 1, ưu tiên 5): MPU6050 50 Hz bằng `vTaskDelayUntil`, BMP280 10 Hz, chạy bộ phát hiện té, đóng gói 25 mẫu. **slowTask**: AHT20 mỗi 10 s |
| `src/net.cpp` | **netTask** (core 0): Wi-Fi, tìm Pi (`MQTT_HOST` qua mDNS → gateway), NTP từ Pi, MQTT (`setBufferSize(2048)`, Last Will), xả vòng đệm, gửi lại sự kiện đến khi có `ack`, nhận lệnh |
| `src/ui.cpp` | **uiTask** (10 ms): nút, máy trạng thái cảnh báo, LED, loa |
| `src/display.cpp` + `src/oled_layout.h` | **displayTask**: OLED (U8g2, chung bus I2C với cảm biến), nhãn tiếng Anh "Lie (70%)", cảnh báo té tiếng Việt; ≤ 2 lần/giây, luôn sáng (giảm sáng sau 60 s không nhấn nút; đổi trong `config.h`) |
| `src/events.cpp` | Sự kiện lưu LittleFS (mỗi sự kiện một file), giờ hệ thống, ngưỡng lưu NVS |
| `lib/fall_detector/` | Phát hiện té bằng ngưỡng, C++ thuần — giống hệt `edge/har_edge/fall_threshold.py` |
| `lib/button/` | Nhận dạng nhấn 1 lần / nhấn đúp / giữ 3 s, chống dội |
| `lib/gyro_cal/`, `lib/upright_cal/` | Hiệu chỉnh độ lệch con quay và hướng đứng thẳng |
| `include/config.h` | Mọi hằng số: tần số, vòng đệm, thời gian hủy, ngoại vi |

## Hành vi

- MPU6050 cấu hình bằng thanh ghi: ±8 g, ±500 °/s, DLPF 21 Hz; gửi giá trị thô int16 theo trục chip (đứng thẳng: X chỉ xuống).
- Hiệu chỉnh con quay (`lib/gyro_cal`): sau khi khởi động, cửa sổ 1,5 s đầu tiên mà thiết bị nằm yên (std < 1 °/s, gia tốc dao động < 0,03 g) cho độ lệch từng trục; thử tối đa 60 s, không đạt thì dùng giá trị NVS lần trước. Mọi mẫu gửi đi và bộ phát hiện té đều dùng giá trị đã trừ độ lệch. Đo lại: `{"cmd":"calibrate_gyro"}`. Mạch hiện tại lệch gx ≈ +13,6 °/s nếu không hiệu chỉnh.
- Chỉ đóng gói dữ liệu sau khi có giờ NTP từ Pi; phát hiện té chạy ngay từ lúc khởi động.
- Mất mạng: vòng đệm 120 gói (60 s, ~37 KB). Có mạng lại thì gửi bù với `replay: true`; quá 60 s bỏ gói cũ nhất (đếm trong `dropped` của status).
- Phát hiện té: rơi (SVM < 0,6 g ≥ 60 ms) → va chạm (> 2,5 g trong 0,5 s) → bất động ở giây 2–3 + tư thế đổi > 50° so với hướng đứng thẳng → `suspected` (khoảng 3 s sau va chạm), loa kêu ngắt quãng, LED đỏ nháy nhanh. 10 s không nhấn nút → `confirmed`, loa kêu liên tục 30 s (nhấn để tắt). Nhấn trong 10 s → `cancelled`. Khi đang thu dataset (màn `REC`) loa không kêu cảnh báo, chỉ LED đỏ + OLED, vì loa rung làm nhiễu gia tốc kế. Hết phiên, `record.py` gửi `cancel_alarm` (sự kiện `cancelled` kèm `"by":"record"`), người đeo không cần nhấn nút.
- Pin: mạch không đo áp pin, `status` gửi `battery_v: null`, OLED hiện giờ thay cho %.
- Ngưỡng đổi lúc chạy: `mosquitto_pub -t har/har01/cmd -m '{"cmd":"set_threshold","impact_g":2.2}'` (lưu NVS). Thử loa/cảnh báo: `{"cmd":"beep","ms":300}`, `{"cmd":"test_alarm"}`.

| Thao tác | Khi nào | Tác dụng |
| --- | --- | --- |
| Nhấn 1 lần | Đang cảnh báo | Hủy (`cancelled`) / tắt loa sau khi đã xác nhận |
| Nhấn 1 lần | Bình thường | Bật màn hình |
| Nhấn đúp | Bình thường | Gửi `marker` (đồng bộ video khi thu dataset) |
| Giữ 3 s | Bình thường | Gửi `sos` |

| Đèn | Ý nghĩa |
| --- | --- |
| Xanh sáng / nháy chậm | Đã kết nối MQTT / đang kết nối |
| Đỏ nháy nhanh / sáng | Đang cảnh báo / lỗi MPU6050 |

## Kiểm tra sau khi nạp

- Serial in `[i2c] bus1 SDA21/SCL22: 0x38 0x3C 0x68 0x77` và `[stat] 50.0 Hz …` mỗi 10 s; trên Pi đếm gói mất bằng `seq` (`link_counts` trong `edge.db`).
- Thả hộp lên nệm → loa kêu; nhấn nút → hủy.
- Tắt Wi-Fi hoặc Mosquitto 30 s rồi bật → `imuQ` tăng rồi xả về 0, Pi nhận gói `replay: true`.
