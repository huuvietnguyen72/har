# Nhật ký tích hợp firmware ESP32 với Pi 4

Ghi lại các vấn đề gặp khi nạp firmware và chạy cùng Pi 4 lần đầu, ngày 16–17/11/2026, cùng cách đã sửa và số đo kiểm chứng. Code đi kèm: PR #3 (OLED, NTP, pin) và PR hiệu chỉnh con quay.

## Cấu hình lúc thử

| Thành phần | Cấu hình |
| --- | --- |
| Bộ đeo | ESP32 DevKit (CP210x, COM6), MPU6050 0x68, AHT20 0x38, BMP280 0x77, OLED SSD1315 0x3C; cấp nguồn qua USB |
| Pi 4 | Raspberry Pi OS Bookworm 64-bit, tên `raspivn`, IP 192.168.12.19 |
| Mạng | Wi-Fi nhà `BIGHOME 02` (router phát cả 2,4 và 5 GHz cùng tên), dải 192.168.12.0/24 |
| Firmware | `firmware/` (espressif32 6.9.0, Arduino), `FW_VERSION 1.0.0` |

## Tóm tắt

| # | Vấn đề | Mức độ | Trạng thái |
| --- | --- | --- | --- |
| 1 | Không dùng được hotspot trên Pi, mạng nhà khác thiết kế | Cao | Đã xử lý bằng cấu hình tay trên Pi |
| 2 | OLED cắm chung bus cảm biến, màn đứng hình cũ | Cao | Đã sửa (`OLED_I2C_BUS`) |
| 3 | NTP kẹt ở router khi mDNS lỡ lần đầu | Cao | Đã sửa |
| 4 | Không có cầu chia áp pin: Pi báo pin yếu sai | Trung bình | Đã sửa (`battery_v: null`) |
| 5 | Con quay lệch +13,8 °/s khi nằm yên | Trung bình | Đã sửa (`lib/gyro_cal`) |
| 6 | Màn OLED khó đọc, tắt sau 15 s | Thấp | Đã làm lại bố cục |
| 7 | Lỡ mẫu MPU6050 không được đếm | Thấp | Đã thêm bộ đếm `lỡ=` |
| 8 | ESP32 mất ~30 s mới biết kết nối TCP đã chết | Thấp | Chưa sửa, đo được |
| 9 | mDNS thỉnh thoảng không trả lời | Thấp | Đã có đường vòng, nên đặt IP cố định |
| 10 | AHT20 đọc nóng (43 °C), gia tốc tĩnh 0,94 g | Thấp | Chưa sửa, do lắp ráp và hiệu chỉnh |
| 11 | Nút cắm GPIO19 thay vì GPIO32: không hủy được cảnh báo té | Cao | Đã sửa (`PIN_BUTTON 19`) |
| 12 | Pi khởi động lại sai giờ 12,3 s, ESP32 giữ giờ sai tới 1 giờ | Trung bình | Đã sửa (`NTP_SYNC_MS 60000`) |
| 13 | MPU6050 hàn xoay 90°: trục X chỉ xuống, không phải Y | Cao | Đã sửa: code theo phần cứng (`UPRIGHT = [-1, 0, 0]`) |

## 1. Mạng: không dùng được hotspot trên Pi

**Hiện tượng.** `secrets.h` còn nguyên bản mẫu (`har-hotspot`, `hargw.local`). Pi đang vào mạng bằng Wi-Fi 5 GHz qua `wlan0` và không có dây LAN. Chạy `edge/deploy/setup-pi.sh` sẽ biến `wlan0` thành hotspot: Pi mất Internet, mất SSH và đổi tên thành `hargw`. ESP32 chỉ bắt được 2,4 GHz.

**Xử lý.** Dùng phương án dự phòng số 3 trong kế hoạch: ESP32 và Pi cùng vào mạng nhà. Router phát 2,4 GHz cùng tên `BIGHOME 02`, nên ESP32 vào được.

- Trên Pi, chạy tay các bước của `setup-pi.sh` nhưng **bỏ phần hotspot và đổi tên máy**, đồng thời đổi dải mạng:
  - ufw: mở 1883/tcp và 123/udp cho `192.168.12.0/24` (thay cho `10.42.0.0/24`), mở thêm **5353/udp (mDNS)** để ESP32 tìm `raspivn.local`.
  - chrony: `allow 192.168.12.0/24`, `local stratum 10` trong `/etc/chrony/conf.d/har.conf`.
  - Mosquitto: tài khoản `har01` (ESP32) và `har-edge` (dịch vụ Pi), mật khẩu ngẫu nhiên 20 ký tự.
- `secrets.h`: `MQTT_HOST "raspivn.local"`, `NTP_HOST ""` (dùng chung địa chỉ broker).

**Còn lại.** `setup-pi.sh` chưa có chế độ "mạng nhà". Nếu cài lại Pi, phải làm tay như trên, hoặc bổ sung tùy chọn vào script.

## 2. OLED cắm chung bus cảm biến

**Hiện tượng.** Màn hiện `R -0 ALTIUDE +2916cm`, là hình còn sót từ chương trình cũ, không phải màn của firmware HAR. Serial không báo lỗi gì, vì `U8g2::begin()` luôn trả `true` dù không có màn.

**Nguyên nhân.** Thêm đoạn dò I2C lúc khởi động thì thấy:

```
[i2c] bus1 SDA21/SCL22: 0x38 0x3C 0x68 0x77
[i2c] bus2 SDA18/SCL19: (không có thiết bị)
```

OLED được cắm chung GPIO21/22 với cảm biến, nhưng firmware vẽ ra bus 2 (GPIO18/19) theo `docs/pinout.md`.

**Sửa (không phải đổi dây).**
- `include/pins.h`: `OLED_I2C_BUS 1` cho OLED chung bus, `2` cho bus riêng như thiết kế.
- Chung bus thì mỗi lần vẽ, màn gửi khung 1 KB (khoảng 25 ms) chiếm bus, trong khi `samplerTask` chỉ chờ `i2cMutex` tối đa 8 ms. Màn được sửa để gửi **từng dải 8 dòng** (128 B, khoảng 3 ms) và nhả mutex giữa các dải.
- Đoạn dò I2C được giữ lại: mỗi lần khởi động in ra OLED đang ở bus nào và có khớp cấu hình không.

**Kiểm chứng.** Màn sáng liên tục 60 s (Pi gửi lệnh `display` mỗi 5 s): `50,0 Hz`, `lỡ=0`.

**Còn lại.** Khi màn đang vẽ, thời điểm đọc MPU6050 có thể lệch tới khoảng 3 ms. Nếu cần dữ liệu huấn luyện thật chuẩn, nên cắm OLED sang GPIO18/19 và đặt `OLED_I2C_BUS 2`.

## 3. NTP kẹt ở router

**Hiện tượng.** Có một lần khởi động `mqtt=1` nhưng `ntp=0` mãi. ESP32 không đóng gói dữ liệu khi chưa có giờ, nên Pi không nhận được gì. `chronyc clients` trên Pi cho thấy không có yêu cầu giờ nào từ lần khởi động đó.

**Nguyên nhân.** Trong `net.cpp`, nếu tìm `raspivn.local` qua mDNS bị lỡ, firmware tạm dùng **gateway** (router). `startNtp()` chạy ngay với địa chỉ router. MQTT kết nối router lỗi nên firmware tìm lại tên và ra Pi, nhưng NTP chỉ khởi động một lần nên vẫn hỏi giờ router.

**Sửa.** Lưu địa chỉ dùng cho NTP (`ntpIp`) và khởi động lại NTP mỗi khi địa chỉ broker đổi (`ntpNeedsStart()`).

**Kiểm chứng.** Trong lần thử tắt broker, log cho thấy mDNS lỡ, chuyển sang router, rồi quay về Pi. NTP đi theo đúng từng bước (`[ntp] máy chủ giờ 192.168.12.1` rồi `192.168.12.19`), và `ntp=1` sau khi kết nối lại.

## 4. Không có cầu chia áp đo pin

**Hiện tượng.**
- GPIO34 đọc 0,284 V. Đây là mức sàn của ADC ESP32, tương đương 0 V: chưa lắp cầu chia 100 kΩ/100 kΩ, và MT3608 cũng chưa có.
- OLED luôn hiện `USB`, kể cả khi đã rút cáp.
- Firmware gửi `battery_v: 0.0` khi không đo được. Vì vậy `har-infer` tạo cảnh báo `low_battery` sai, và đèn đỏ có thể nháy báo pin yếu.

**Sửa.**
- `config.h`: `BATTERY_PRESENT_V 2.5f`. Đo dưới mức này thì `battery_v = NAN`, coi như không có pin.
- `status` gửi `"battery_v": null`. Pi đã bỏ qua `null`, không tạo cảnh báo.
- OLED: góc phải hiện **giờ Việt Nam HH:MM**. Khi lắp cầu chia áp thì tự đổi sang `%` pin.

**Kiểm chứng.** Pi nhận `"battery_v":null`, và không có cảnh báo `lowbat` mới.

## 5. Con quay lệch khi nằm yên

**Hiện tượng.** Phân tích 15 phút dữ liệu lúc mạch nằm trên bàn:

| Trục | Trung bình (°/s) | Std trong cửa sổ 1,5 s nằm yên |
| --- | --- | --- |
| gx | +13,79 | 0,19 |
| gy | +4,20 | 0,05 |
| gz | +0,43 | 0,07 |

Độ lớn con quay lúc nằm yên khoảng 15 °/s, phân vị 99 % là 30,5 °/s. Bộ phát hiện té dùng ngưỡng "bất động" `still_gyro_dps = 30`, nên đã sát ngưỡng ngay cả khi nằm yên. Dữ liệu huấn luyện model cũng bị lệch theo.

**Sửa.** Thư viện mới `lib/gyro_cal/gyro_cal.h` (C++ thuần, có test native):
- Sau khi khởi động, cửa sổ 1,5 s đầu tiên mà thiết bị nằm yên cho độ lệch từng trục. Điều kiện nằm yên: std con quay < 1 °/s, SVM dao động < 0,03 g, |trung bình| < 40 °/s.
- Thử tối đa `GYRO_CAL_TRIES = 40` cửa sổ (60 s). Không đạt thì dùng giá trị lưu NVS lần trước.
- Mọi mẫu gửi đi và bộ phát hiện té đều dùng giá trị đã trừ độ lệch. Kết quả được lưu NVS (namespace `imu`).
- Lệnh `{"cmd":"calibrate_gyro"}` để đo lại. `status` có thêm `gyro_cal` (`measured` / `nvs` / `none`) và `gyro_bias_dps`.
- Việc ghi NVS và in Serial nằm ở `slowTask`, không chạy trong `samplerTask`, để không làm trễ nhịp 50 Hz.

**Kiểm chứng.**
- Hiệu chỉnh xong khoảng 2 s sau khi khởi động, độ lệch đo được `13,69 / 4,21 / 0,44 °/s`.
- Sau hiệu chỉnh, 750 mẫu nằm yên trên Pi có trung bình `−0,03 / −0,02 / −0,01 °/s`, độ lớn trung bình 0,08 °/s.
- 4 test native mới đều đạt: nằm yên, đang lắc rồi thử lại, quay đều, bão hòa int16. Tổng 10/10.

**Còn lại.** Độ lệch đổi theo nhiệt độ. Mạch đang nóng lên (xem mục 10), nên khi thu dataset dài nên gửi `calibrate_gyro` hoặc khởi động lại mạch lúc đang nằm yên.

## 6. Màn OLED khó đọc

Các yêu cầu được xử lý lần lượt:

| Vấn đề | Thay đổi |
| --- | --- |
| Màn tắt sau 15 s | `DISPLAY_TIMEOUT_MS 0` (luôn sáng), `DISPLAY_DIM_MS 60000` (giảm sáng để đỡ lưu ảnh), độ sáng tối đa khi khởi động |
| Chữ nhỏ, chật | Bỏ tên thiết bị, nhiệt độ, độ ẩm, dBm; nhãn và % tin cậy gộp một dòng |
| Phóng to tiếng Việt làm mất dấu chồng ("Nằm" → "Năm") | Phát hiện nhờ xem trước trên PC; sau đó chuyển sang nhãn tiếng Anh |
| Ký tự "…" không có trong font, màn trống | Đổi thành `...` |
| `noNTP` đè lên chữ `USB` | Trạng thái gộp thành 1 từ: `noWiFi` → `WiFi..` → `NTP..` → `MQTT` |
| Dòng "Nhấn nút để hủy 10s" dài quá 128 px | Rút còn "Nhấn để hủy 10s" |

Bố cục cuối, chữ thường, không đậm:

```
MQTT              14:35     ← kết nối | giờ (hoặc % pin)
WiFi: BIGHOME 02            ← tên Wi-Fi (cắt "..." nếu dài)
─────────────────────────
       Lie (70%)            ← nhãn tiếng Anh (độ tin cậy)
```

Cảnh báo té vẫn giữ tiếng Việt có dấu. Bố cục nằm trong `src/oled_layout.h`, viết bằng API C của U8g2, nên biên dịch được trên PC với U8g2 `clib` để xuất ảnh xem trước. Nhờ đó các lỗi ở bảng trên được bắt trước khi nạp.

## 7. Lỡ mẫu MPU6050 không được đếm

Khi `samplerTask` không lấy được `i2cMutex` trong 8 ms hoặc I2C lỗi, mẫu trước được lặp lại để giữ nhịp, nhưng không có thông báo nào. Dòng `[stat]` giờ có thêm `lỡ=`.

Số đo: 0 trong phần lớn các lần chạy. Thỉnh thoảng có 1 lần ngay sau khi khởi động hoặc khi xả vòng đệm sau mất mạng, tức khoảng 1 trên 4.000 mẫu.

## 8. Mất kết nối và gửi bù

| Cách thử | Kết quả |
| --- | --- |
| Tắt Mosquitto 30 s | ESP32 phát hiện ngay (`state=-2`), vòng đệm lên 56 gói rồi xả hết, Pi nhận 59 gói `replay`, `bỏ=0`, không reset. `har-ingest` báo mất 32 gói, nhưng đó là do cách thử: `har-ingest` cũng mất broker và chưa đăng ký lại kịp khi ESP32 gửi bù. |
| Chặn riêng ESP32 bằng iptables 30 s (giống mất Wi-Fi) | Vòng đệm lên 83 gói, xả hết sau khi mở lại, Pi nhận **87 gói `replay`**. Mất 4 gói (khoảng 2 s), không reset. Đạt tiêu chí giai đoạn 2. |

**Còn lại.** Khi bị chặn, ESP32 vẫn báo `mqtt=1` khoảng 30 s. Kết nối TCP đã chết nhưng chưa bị phát hiện cho tới khi hết keepalive, và 4 gói đã ghi vào socket chết đó bị mất. Có thể giảm bằng cách hạ keepalive của PubSubClient, hoặc giữ lại gói cho tới khi có ack (QoS 1). Chưa làm, vì mức mất hiện tại vẫn dưới 1 %.

## 9. mDNS không ổn định

Thỉnh thoảng `MDNS.queryHost("raspivn")` không trả lời trong 2 s, và firmware chuyển tạm sang gateway. Sau sửa lỗi ở mục 3, firmware tự quay về Pi trong vài giây. Để chắc chắn, nên đặt **IP cố định cho Pi** trên router (DHCP reservation) và ghi IP vào `MQTT_HOST`.

## 10. Số đo cảm biến cần để ý

| Cảm biến | Quan sát | Nhận định |
| --- | --- | --- |
| AHT20 | 31 °C / 98 % RH lúc mới bật, sau khoảng 1 giờ thành 43 °C / 72 % | Cảm biến bị hâm nóng bởi ESP32 hoặc mạch nguồn. Nên đặt xa nguồn nhiệt, khoan lỗ thông khí khi đóng hộp. Không dùng làm đặc trưng nhận dạng. |
| MPU6050 gia tốc | SVM lúc nằm yên 0,942 ± 0,007 g, thay vì 1,0 g | Sai số offset hoặc tỉ lệ của gia tốc kế, chưa hiệu chỉnh. Ảnh hưởng nhỏ tới ngưỡng té (0,4 g, 2,5 g, cửa sổ bất động 0,8–1,2 g). Có thể hiệu chỉnh 6 mặt sau. |
| BMP280 | 100.954 Pa ± 2,8 Pa, đúng 10 Hz | Bình thường |

## 11. Nút cắm nhầm chân: không hủy được cảnh báo té

**Hiện tượng.** Thả hộp lên nệm thì phát hiện té đúng (lực va chạm 8,5 g và 12,1 g), Pi nhận `suspected`, nhưng nhấn nút trong 10 s vẫn ra `confirmed`. Nhấn đúp và giữ 3 s cũng không có tác dụng.

**Chẩn đoán.**
1. Thêm log cho nút: Serial in mức chân lúc khởi động và từng thao tác nhấn; `status` có `btn_presses`, `btn_level`. Kết quả: GPIO32 luôn ở mức HIGH, nhấn nút không tạo ra sự kiện nào.
2. Nạp một chương trình dò chân tạm thời, theo dõi 11 GPIO còn trống (4, 5, 13, 14, 16, 17, 18, 19, 23, 32, 33). Pha A bật điện trở kéo lên để tìm nút nối GND, pha B bật kéo xuống để tìm nút nối 3V3. Pha A cho thấy **GPIO19 xuống LOW mỗi lần nhấn**: nút nối giữa GPIO19 và GND.

**Sửa (không phải đổi dây).**
- `include/pins.h`: `PIN_BUTTON 19`, ghi chú thiết kế gốc là GPIO32.
- GPIO19 trùng SCL của bus I2C 2. Bus 2 chỉ được bật khi không trùng chân nút (`BUS2_PINS_FREE`); `OLED_I2C_BUS 2` cùng lúc nút ở GPIO18/19 sẽ báo lỗi biên dịch.

**Kiểm chứng (17/11, 00:46–00:48).**

| Thao tác | ESP32 | Pi |
| --- | --- | --- |
| Nhấn 1 lần | `[btn] 1-lần` | — |
| Nhấn đúp | `[btn] nhấn-đúp` | `marker`, 5 lần |
| Giữ 3 s | `[btn] giữ-3s` | `sos` → cảnh báo mức cao, đã báo trong 0,3 s; các SOS dưới 60 s được gộp |
| Thả hộp, nhấn trong 10 s | — | `suspected` lúc 00:47:39, `cancelled` lúc 00:47:41, cảnh báo `cancelled: true`, `notify: false` |

Còi kêu ngắt quãng khi nghi té và bíp khi nhấn; LED xanh và đỏ hoạt động đúng (người dùng xác nhận).

**Bài học.** Mạch lắp theo một chương trình thử cũ nên chân khác `docs/pinout.md` (OLED ở bus 1, nút ở GPIO19). Khi nhận mạch mới, nên chạy chương trình dò chân và dò I2C trước khi nạp firmware.

## 12. Pi sai giờ sau khi khởi động lại

**Hiện tượng.** Phiên thu thử `har01_S00_walk_20261117-005924` có dấu thời gian mẫu sớm hơn `start` của phiên 12,35 s.

**Nguyên nhân.** Pi 4 không có RTC. Sau khi khởi động lại lúc 00:49:52, giờ Pi sai 12,3 s; chrony chỉnh lúc 00:50:25 (`System clock was stepped by 12.337301 seconds`). ESP32 đã lấy giờ từ Pi lúc 00:50:03, trước khi Pi được chỉnh, và mặc định ESP-IDF 1 giờ mới hỏi giờ lại.

**Sửa.** `sntp_set_sync_interval(NTP_SYNC_MS)` trước `configTime`, `NTP_SYNC_MS 60000` trong `config.h`.

**Kiểm chứng.** `chronyc clients` cho thấy ESP32 hỏi giờ khoảng mỗi 60 s. Lệch đồng hồ ESP32 so với Pi (mẫu cuối của gói so với lúc Pi nhận, 20 gói) có trung vị −20 ms, tức chỉ là độ trễ đóng gói và mạng.

**Còn lại.** Nếu demo không có Internet, giờ Pi lấy từ lần tắt trước và có thể lệch nhiều; cần module RTC cho Pi hoặc chia sẻ Internet từ điện thoại.

## 13. Hướng trục MPU6050: theo phần cứng

**Hiện tượng.** Phiên đi bộ thử: gia tốc trung bình `ax ≈ -0,97 g, ay ≈ -0,01 g, az ≈ -0,12 g`. Kế hoạch và code giả định đứng thẳng thì `ay ≈ -1 g` (Y chỉ xuống), nhưng module đã hàn xoay 90° nên **trục X chỉ xuống**. Hậu quả với quy ước cũ: luật nhận dạng trên Pi đoán 44/58 cửa sổ là `walk`, còn lại `lie`, `stairs_*`; bộ phát hiện té coi người đeo luôn "đã đổi tư thế" (nghiêng 90°), dễ báo nhầm khi ngồi phịch xuống ghế.

**Quyết định.** Phần cứng đã hàn, khó đổi. Code và tài liệu theo phần cứng, không đổi trục để giống kế hoạch.

**Sửa.**
- Firmware: dữ liệu gửi đi là trục chip, không đổi trục. `FallParams::up = (-1, 0, 0)`. Test native viết lại theo hệ X chỉ xuống.
- Pi: `features.UPRIGHT = [-1, 0, 0]` (dùng cho góc nghiêng, luật nhận dạng, ngưỡng té trên Pi). `synth.py` sinh dữ liệu giả lập theo cùng hệ trục. Metadata phiên ghi `"hông phải, X chỉ xuống đất"`.

**Kiểm chứng.** Phiên đi bộ thật với quy ước mới: góc nghiêng trung bình 6,4°, luật nhận dạng đoán đúng **58/58** cửa sổ là `walk`. Dữ liệu giả lập: đứng 0,2°, ngồi 48°, nằm 89,8°. Test: firmware 10/10, edge 17/17.

**Lưu ý.** Hình 3 trong `hardware/So_do_lap_bo_deo_HAR.html` vẫn vẽ trục Y chỉ xuống theo thiết kế ban đầu; mạch thật khác hình này.

## Đối chiếu tiêu chí trong kế hoạch

| Giai đoạn | Tiêu chí | Kết quả |
| --- | --- | --- |
| 1 | I2C thấy 0x68, 0x38, 0x76/0x77 | ✅ |
| 1 | MT3608, chạy bằng pin 10 phút | ⏳ Chưa có MT3608 |
| 1 | Đo pin GPIO34 lệch < 0,05 V | ➖ Không lắp cầu chia áp |
| 2 | 30 phút, mất < 1 %, 50 ± 0,5 Hz | ✅ Mất 0 gói, 50,000 Hz |
| 2 | Mất mạng 30 s, gửi bù, không reset | ✅ 87 gói replay, mất 4 gói |
| 2 | Thả hộp lên nệm, còi kêu, nhấn nút hủy | ✅ Sau khi sửa chân nút (mục 11) |
| 2 | Mật khẩu không lên Git | ✅ `**/secrets.h` trong `.gitignore` |
| 3 | Dịch vụ tự chạy khi bật Pi | ✅ systemd enable; chưa thử khởi động lại Pi |
| 3 | File dữ liệu 50 mẫu/s, có áp suất và thời gian | ✅ `data/raw/har01/<ngày>/<giờ>_imu.csv`, `_env.csv` |
| 3 | Outbox xả hết sau mất Internet | ⏳ Chưa có VPS, `CLOUD_BACKEND=console` |

## Việc tiếp theo

1. ~~Thử tay: thả hộp, nhấn hủy, nhấn đúp, giữ 3 s~~ — đã xong (mục 11).
2. Thử khởi động lại Pi, xác nhận ESP32 tự kết nối lại trong 30 s.
3. Đặt IP cố định cho Pi trên router.
4. Gắn hộp lên đai ở hông phải, trục Y chỉ xuống, cấp nguồn bằng sạc dự phòng qua USB cho tới khi có MT3608. Sau đó chạy thử một phiên `record.py` trước khi thu dataset (giai đoạn 4).
5. Tùy chọn: hiệu chỉnh gia tốc kế 6 mặt; hạ keepalive MQTT; bổ sung chế độ "mạng nhà" cho `setup-pi.sh`.
