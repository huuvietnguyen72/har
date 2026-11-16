# Phần cứng

[`Datasheet_HAR01.html`](Datasheet_HAR01.html): sơ đồ mạch, sơ đồ hệ thống, ID chip I2C, đo tải từng chân, bộ nhớ flash, trạng thái lúc đọc. Bảng chân: [`../docs/pinout.md`](../docs/pinout.md).

## Mạch

- ESP32 DevKit (ESP32-D0WD-V3, flash 4 MB, CP210x).
- Một bus I2C GPIO21/22: MPU6050 (0x68), board AHT20 + BMP280 (0x38 + 0x77), OLED 0,96" (0x3C).
- Nút GPIO19 nối GND; loa GPIO25 qua tầng transistor; LED xanh GPIO26, LED đỏ GPIO27, sáng khi HIGH.
- Nguồn: pin Li-ion → mạch sạc → tăng áp 5 V → VIN, hoặc USB. Không có cầu chia áp đo pin (`battery_v: null`). Không có motor rung.
- MPU6050: đeo ở hông phải, đứng thẳng thì **trục X chỉ xuống đất** (ax ≈ −1 g).

## Lưu ý khi đeo và thu dữ liệu

- Đeo ở hông phải, trục X của MPU6050 chỉ xuống đất, giữ cố định cho mọi lần thu.
- Trước mỗi người đeo, chạy hiệu chỉnh hướng đứng thẳng (`record.py` tự gửi `calibrate_upright`).
- Nếu thay mạch tăng áp, chỉnh đúng 5,0 V **trước** khi nối ESP32.

## Nên bổ sung

Ảnh mạch và hộp; số đo dòng tiêu thụ và thời gian chạy bằng pin; mã các linh kiện chưa đối chiếu (transistor loa, điện trở LED, module sạc và tăng áp).
