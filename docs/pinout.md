# Bảng chân ESP32 DevKit

Theo mạch đang hàn, đo trên thiết bị ngày 17/11/2026: quét I2C, đọc ID chip, đo tải trên từng chân. Chi tiết số đo: [`hardware/Datasheet_HAR01.html`](../hardware/Datasheet_HAR01.html). Firmware: [`firmware/include/pins.h`](../firmware/include/pins.h).

| Chức năng | Chân | Ghi chú |
| --- | --- | --- |
| I2C SDA / SCL | GPIO21 / GPIO22 | Một bus, 400 kHz, 3 module / 4 địa chỉ: MPU6050 (0x68), board AHT20 + BMP280 (0x38 + 0x77), OLED 0,96" (0x3C). `OLED_I2C_BUS 1` |
| Nút nhấn | GPIO19 | Nút nối GND, `INPUT_PULLUP`, nhấn = LOW |
| Loa | GPIO25 | Qua tầng transistor (đo thấy mối B-E xuống GND); mức HIGH = kêu, `BUZZER_PASSIVE 0` |
| LED xanh | GPIO26 | Sáng khi HIGH; đã nối MQTT / đang nối |
| LED đỏ | GPIO27 | Sáng khi HIGH; cảnh báo, lỗi cảm biến |

Chân trống (đo thả nổi): GPIO18, 32, 33, 34, 35, 36, 39.

MPU6050: đeo ở hông phải, đứng thẳng thì trục X chỉ xuống đất (ax ≈ −1 g).

Nguồn: USB 5 V hoặc pin Li-ion → mạch sạc → tăng áp 5 V → VIN. Không có cầu chia áp đo pin: firmware đọc GPIO34 (`PIN_BATTERY`), đọc dưới 2,5 V nên gửi `battery_v: null`, OLED hiện giờ thay cho %, không có cảnh báo pin yếu. Không có motor rung (`USE_VIBRATION 0`).

Giá trị điện trở, mã transistor và tên module sạc/tăng áp chưa đối chiếu trên mạch nên chưa ghi.
