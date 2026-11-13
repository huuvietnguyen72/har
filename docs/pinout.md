# Bảng chân ESP32 DevKit

| Chức năng | Chân | Ghi chú |
| --- | --- | --- |
| I2C bus 1 SDA / SCL | GPIO21 / GPIO22 | MPU6050 (0x68, AD0 nối GND), AHT20 (0x38), BMP280 (0x76 hoặc 0x77) |
| I2C bus 2 SDA / SCL | GPIO18 / GPIO19 | OLED 0,96" SSD1315 (0x3C), tách riêng để không làm lệch nhịp lấy mẫu 50 Hz |
| Còi | GPIO25 | Qua 1 kΩ vào S8050, diode 1N4148 chặn xung ngược |
| LED xanh | GPIO26 | 220 Ω; đang chạy, đã kết nối |
| LED đỏ | GPIO27 | 220 Ω; pin yếu, mất Wi-Fi, lỗi cảm biến, đang cảnh báo |
| Nút nhấn | GPIO32 | `INPUT_PULLUP`, nhấn nối GND |
| Motor rung (tùy chọn) | GPIO33 | Mắc giống còi |
| Đo áp pin | GPIO34 | Cầu chia 100 kΩ / 100 kΩ (pin 4,2 V → 2,1 V); chỉ vào, không có pull-up |

Nguồn: pin 18650 → TP4056 → công tắc → MT3608 (chỉnh đúng 5,0 V trước khi nối) → chân 5V ESP32.
