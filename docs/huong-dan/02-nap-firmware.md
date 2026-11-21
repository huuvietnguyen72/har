# 2. Nạp firmware cho bộ đeo

Firmware ESP32 dùng PlatformIO + Arduino (espressif32 6.9.0), FreeRTOS 5 task. Cấu trúc mã nguồn và hành vi chi tiết: [`../../firmware/README.md`](../../firmware/README.md).

## 2.1. Cài đặt trên laptop

1. VS Code + extension **PlatformIO IDE**.
2. Driver USB **CP210x** (Silicon Labs) nếu Windows không nhận cổng COM.
3. Clone repo: `git clone https://github.com/huuvietnguyen72/har.git`.
4. Trong VS Code, **mở thư mục `firmware/`**, không mở gốc repo. Mở gốc repo thì PlatformIO không thấy `platformio.ini` của firmware.

## 2.2. Điền thông tin mạng: `secrets.h`

```bash
cd firmware/include
cp secrets.example.h secrets.h
```

Sửa `secrets.h` (file này nằm trong `.gitignore`, **không bao giờ commit**):

| Hằng số | Giá trị cho hệ thống hiện tại |
| --- | --- |
| `WIFI_SSID`, `WIFI_PASSWORD` | Wi-Fi nhà, băng tần **2,4 GHz** |
| `MQTT_HOST` | `"raspivn.local"` hoặc IP Pi `"192.168.12.19"` (IP chắc hơn, xem sự cố mDNS) |
| `MQTT_USER`, `MQTT_PASSWORD` | Tài khoản `har01` tạo trên Mosquitto của Pi ([bước 3](03-cai-dat-pi.md#34-mosquitto)) |
| `NTP_HOST` | `""`: lấy giờ từ cùng máy với MQTT (chrony trên Pi) |
| `DEVICE_ID` | `"har01"` |

File mẫu vẫn ghi `har-hotspot` / `hargw.local` của phương án Pi phát hotspot; nhóm không dùng phương án đó (xem [bước 3](03-cai-dat-pi.md)).

## 2.3. Nạp và xem Serial

Cắm ESP32 bằng cáp USB **có dây dữ liệu** (cáp chỉ sạc thì máy không thấy cổng COM).

```bash
cd firmware
pio run -e esp32dev -t upload      # biên dịch + nạp
pio device monitor                 # Serial 115200
```

Trong VS Code dùng nút ✓ (Build), → (Upload), 🔌 (Monitor) ở thanh dưới. Nếu nạp báo không kết nối được, giữ nút **BOOT** trên ESP32 khi bắt đầu nạp.

## 2.4. Kiểm tra sau khi nạp

Serial lúc khởi động và mỗi 10 s phải có:

```
[i2c] bus1 SDA21/SCL22: 0x38 0x3C 0x68 0x77
[gyro] đã hiệu chỉnh: bias 13.69 4.21 0.44 °/s (lưu NVS)   ← đặt yên trên bàn ~2 s sau khi bật
[ntp] máy chủ giờ 192.168.12.19
[stat] 50.0 Hz, lỡ=0 imuQ=0 envQ=0 bỏ=0 wifi=1 mqtt=1 ntp=1 pin=nanV heap=...
```

| Kiểm tra | Đạt khi |
| --- | --- |
| I2C | Đủ 4 địa chỉ |
| Nhịp lấy mẫu | `50.0 Hz`, `lỡ=0` (thỉnh thoảng 1 ngay sau khởi động là bình thường) |
| Kết nối | `wifi=1 mqtt=1 ntp=1`; LED xanh sáng liên tục, OLED góc trái `MQTT` |
| Pi nhận dữ liệu | Trên Pi: `mosquitto_sub -u har-edge -P '<mật khẩu>' -t 'har/har01/status' -C 1` |
| Còi, cảnh báo | Từ Pi: `mosquitto_pub ... -t har/har01/cmd -m '{"cmd":"beep","ms":300}'`; `{"cmd":"test_alarm"}` thì còi kêu ngắt quãng, nhấn nút để hủy |
| Mất mạng | Tắt Wi-Fi router 30 s rồi bật: vòng đệm tăng rồi xả về 0, Pi nhận gói `replay: true` |

ESP32 **chỉ gửi dữ liệu khi đã có giờ** từ Pi (`ntp=1`). `mqtt=1` mà `ntp=0` thì Pi không nhận được gói IMU nào.

## 2.5. Test logic trên máy tính

Các thư viện C++ thuần (nút, máy trạng thái cảnh báo, hiệu chỉnh con quay, hiệu chỉnh hướng đứng, luồng hiệu chỉnh bằng nút) có test chạy trên laptop, không cần ESP32:

```bash
cd firmware
pio test -e native        # cần gcc/g++ (Windows: MSYS2 hoặc MinGW trong PATH)
```

Kết quả hiện tại: 21/21. Sửa bất cứ gì trong `firmware/lib/` thì chạy lại trước khi mở PR.

## 2.6. Đổi cấu hình không cần nạp lại

Gửi lệnh MQTT tới `har/har01/cmd` (từ Pi hoặc qua Telegram):

| Lệnh | Tác dụng |
| --- | --- |
| `{"cmd":"set_threshold","impact_g":2.2}` | Đổi ngưỡng té, lưu NVS |
| `{"cmd":"calibrate_gyro"}` | Đo lại độ lệch con quay (đặt yên) |
| `{"cmd":"calibrate_upright","id":"x"}` | Hiệu chỉnh hướng đứng (người đeo đứng thẳng); hoặc nhấn nút 3 lần, `/hieuchinh` |
| `{"cmd":"set_upright","up":[-1,0,0]}` | Đặt tay hướng đứng (khôi phục) |
| `{"cmd":"test_alarm"}`, `{"cmd":"cancel_alarm"}` | Bật/hủy cảnh báo té thử |
| `{"cmd":"beep","ms":300}` | Còi (`ms: 0` để dừng) |

Hằng số khác (tần số, vòng đệm, thời gian hủy 10 s, độ sáng màn) nằm trong `firmware/include/config.h`; đổi thì phải nạp lại.

## Sự cố đã gặp

Chi tiết: [`../firmware-integration.md`](../firmware-integration.md).

| Sự cố | Nguyên nhân | Xử lý | Mục |
| --- | --- | --- | --- |
| `mqtt=1` nhưng `ntp=0` mãi, Pi không nhận dữ liệu | mDNS lỡ lần đầu, firmware tạm dùng router làm máy NTP rồi không đổi lại | Sửa firmware: khởi động lại NTP mỗi khi địa chỉ broker đổi | 3 |
| Thỉnh thoảng không tìm thấy `raspivn.local` | mDNS trên mạng nhà không ổn định | Firmware tự thử lại; nên đặt **IP cố định cho Pi** trên router và ghi IP vào `MQTT_HOST` | 9 |
| Dấu thời gian lệch 12 s so với Pi | Pi không có RTC, khởi động lại sai giờ; ESP32 lấy giờ sai rồi 1 giờ mới hỏi lại | `NTP_SYNC_MS 60000`: hỏi giờ mỗi 60 s | 12 |
| Mất mạng: Pi mất 4 gói (~2 s) | ESP32 mất ~30 s mới biết kết nối TCP đã chết, gói ghi vào socket chết bị mất | Chưa sửa (dưới 1 %); cách sửa: hạ keepalive hoặc QoS 1 | 8 |
| Cảnh báo té xác nhận ngay, không cho 10 s hủy | Lỗi trừ thời gian kiểu không dấu khi `millis()` vừa tăng 1 ms | Viết lại thành `lib/alarm_fsm` có test; **lỗi nghiêm trọng**: khi dùng thật người đeo không hủy được báo nhầm | 18 |
| Bộ đeo bỏ lọt cú ngã thật 3,5 g | Ngưỡng rơi tự do và "bất động" quá chặt so với té thật | Chỉnh theo dữ liệu té thật: 0,6 g / 60 ms / xét yên ở giây 2–3 | 15 |
| Màn OLED: tiếng Việt mất dấu khi phóng to, ký tự `…` làm màn trống, chữ tràn 128 px | Giới hạn font U8g2 | Nhãn tiếng Anh, `...`; bố cục trong `oled_layout.h` xuất ảnh xem trước trên PC trước khi nạp | 6 |
| Lỡ mẫu MPU6050 không ai biết | Không có bộ đếm | Thêm `lỡ=` vào dòng `[stat]` | 7 |
| Model thấy té nhưng còi không kêu | Còi chỉ bật khi bộ đeo tự phát hiện | Sửa phía Pi: Pi gửi `test_alarm` (không phải nạp lại firmware) | 24 |

**Lưu ý khi sửa firmware:**
- `pins.h` phải khớp mạch thật; đổi chân thì cập nhật `docs/pinout.md`.
- Không làm việc chậm (ghi flash, in Serial dài) trong `samplerTask`: làm lệch nhịp 50 Hz. Đặt ở `slowTask`.
- Ngưỡng té ở firmware (`FallParams`) và ở Pi (`edge/har_edge/fall_threshold.py`) phải giống nhau, vì Pi dùng bản Python để đánh giá.
