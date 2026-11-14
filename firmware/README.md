# Firmware ESP32

PlatformIO + Arduino framework (espressif32 6.9.0). Thiết kế ở kế hoạch, giai đoạn 2. Chân: [`include/pins.h`](include/pins.h) / [`../docs/pinout.md`](../docs/pinout.md). Payload: [`../docs/mqtt.md`](../docs/mqtt.md).

## Bắt đầu

1. VS Code + extension PlatformIO, **mở thư mục `firmware/`** (không phải gốc repo).
2. Copy `include/secrets.example.h` thành `include/secrets.h`, điền SSID, mật khẩu Wi-Fi, MQTT (`secrets.h` nằm trong `.gitignore`).
3. Hiệu chỉnh `BATTERY_CAL` trong `include/config.h` theo số đo đồng hồ (giai đoạn 1).
4. `pio run -e esp32dev -t upload && pio device monitor`
5. Test logic trên máy tính (cần gcc): `pio test -e native`

## Cấu trúc

| File | Việc làm |
| --- | --- |
| `src/main.cpp` | Tạo hàng đợi, mutex, 5 task FreeRTOS; in thống kê Serial mỗi 10 s |
| `src/sensors.cpp` | **samplerTask** (core 1, ưu tiên 5): MPU6050 50 Hz bằng `vTaskDelayUntil`, BMP280 10 Hz, chạy bộ phát hiện té, đóng gói 25 mẫu. **slowTask**: AHT20 + áp pin mỗi 10 s |
| `src/net.cpp` | **netTask** (core 0): Wi-Fi, tìm Pi (`hargw.local` qua mDNS → gateway), NTP từ Pi, MQTT (`setBufferSize(2048)`, Last Will), xả vòng đệm, gửi lại sự kiện đến khi có `ack`, nhận lệnh |
| `src/ui.cpp` | **uiTask** (10 ms): nút, máy trạng thái cảnh báo, LED, còi |
| `src/display.cpp` | **displayTask**: OLED trên bus I2C thứ hai (U8g2, font tiếng Việt), ≤ 2 lần/giây, tắt sau 15 s |
| `src/events.cpp` | Sự kiện lưu LittleFS (mỗi sự kiện một file), giờ hệ thống, ngưỡng lưu NVS |
| `lib/fall_detector/` | Phát hiện té bằng ngưỡng, C++ thuần — giống hệt `edge/har_edge/fall_threshold.py` |
| `lib/button/` | Nhận dạng nhấn 1 lần / nhấn đúp / giữ 3 s, chống dội |
| `include/config.h` | Mọi hằng số: tần số, vòng đệm, thời gian hủy, pin, ngoại vi tùy chọn |

## Hành vi

- MPU6050 cấu hình bằng thanh ghi: ±8 g, ±500 °/s, DLPF 21 Hz; gửi giá trị thô int16.
- Chỉ đóng gói dữ liệu sau khi có giờ NTP từ Pi; phát hiện té chạy ngay từ lúc khởi động.
- Mất mạng: vòng đệm 120 gói (60 s, ~37 KB). Có mạng lại thì gửi bù với `replay: true`; quá 60 s bỏ gói cũ nhất (đếm trong `dropped` của status).
- Phát hiện té: rơi tự do (SVM < 0,4 g ≥ 80 ms) → va chạm (> 2,5 g trong 0,5 s) → bất động + tư thế đổi sau 2 s → `suspected`, còi ngắt quãng, LED đỏ nháy nhanh. 10 s không nhấn nút → `confirmed`, còi liên tục 30 s (nhấn để tắt còi). Nhấn trong 10 s → `cancelled`.
- Ngưỡng đổi lúc chạy: `mosquitto_pub -t har/har01/cmd -m '{"cmd":"set_threshold","impact_g":2.2}'` (lưu NVS). Thử còi/cảnh báo: `{"cmd":"beep","ms":300}`, `{"cmd":"test_alarm"}`.

| Thao tác | Khi nào | Tác dụng |
| --- | --- | --- |
| Nhấn 1 lần | Đang cảnh báo | Hủy (`cancelled`) / tắt còi sau khi đã xác nhận |
| Nhấn 1 lần | Bình thường | Bật màn hình |
| Nhấn đúp | Bình thường | Gửi `marker` (đồng bộ video khi thu dataset) |
| Giữ 3 s | Bình thường | Gửi `sos` |

| Đèn | Ý nghĩa |
| --- | --- |
| Xanh sáng / nháy chậm | Đã kết nối MQTT / đang kết nối |
| Đỏ nháy nhanh / sáng / nháy chậm | Đang cảnh báo / lỗi MPU6050 / pin < 3,4 V |

## Kiểm tra tiêu chí giai đoạn 2

- Serial in `[stat] 50.0 Hz …` mỗi 10 s; trên Pi đếm gói mất bằng `seq` (`link_counts` trong `edge.db`).
- Thả hộp lên nệm → còi kêu; nhấn nút → hủy.
- Tắt hotspot 30 s rồi bật → `imuQ` tăng rồi xả về 0, Pi nhận gói `replay: true`.
- Còi thụ động hoặc motor rung: bật `BUZZER_PASSIVE` / `USE_VIBRATION` trong `config.h`.
