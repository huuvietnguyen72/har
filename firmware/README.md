# Firmware ESP32

PlatformIO + Arduino framework. Thiết kế chi tiết ở kế hoạch, giai đoạn 2.

## Bắt đầu

1. Cài VS Code + extension PlatformIO.
2. Copy `include/secrets.example.h` thành `include/secrets.h` rồi điền SSID, mật khẩu Wi-Fi, thông tin MQTT. `secrets.h` đã nằm trong `.gitignore`.
3. `pio run -t upload && pio device monitor`

## Việc cần làm

- [ ] Task lấy mẫu (core 1): MPU6050 50 Hz (±8 g, ±500 °/s, DLPF 21 Hz), BMP280 10 Hz, AHT20 và áp pin mỗi 10 s
- [ ] Task mạng (core 0): gói 25 mẫu, MQTT (`setBufferSize(2048)`), tự kết nối lại, Last Will
- [ ] Phát hiện té bằng ngưỡng: rơi tự do → va chạm → bất động → 10 s chờ hủy
- [ ] Nút: nhấn 1 lần hủy, nhấn đúp `marker`, giữ 3 s `sos`
- [ ] LED trạng thái, còi
- [ ] Vòng đệm 60 s khi mất mạng, sự kiện té lưu LittleFS
- [ ] OLED trên bus I2C thứ hai (U8g2), task riêng ưu tiên thấp, ≤ 2 lần/giây, tự tắt sau 15 s
- [ ] Đồng bộ giờ NTP từ Pi

Chân: xem [`include/pins.h`](include/pins.h) và [`../docs/pinout.md`](../docs/pinout.md). Payload: [`../docs/mqtt.md`](../docs/mqtt.md).
