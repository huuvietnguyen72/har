# Vận hành hằng ngày

Các việc hay làm với hệ thống đang chạy. Cài đặt từ đầu: [`edge/README.md`](../edge/README.md), [`cloud/README.md`](../cloud/README.md), [`firmware/README.md`](../firmware/README.md). Lịch sử vấn đề và cách sửa: [`firmware-integration.md`](firmware-integration.md).

| Thành phần | Ở đâu |
| --- | --- |
| Dashboard | `https://har-cloud.har-cloud.workers.dev` (tài khoản tạo bằng `admin.mjs`, không tự đăng ký) |
| Pi | `ssh pi@192.168.12.19` (hoặc `pi@raspivn.local`); code `~/har`, cấu hình `~/har/edge/.env`, dữ liệu `~/har/edge/data/` |
| Telegram | bot `@harnoti_bot`, chỉ nhận lệnh từ `TELEGRAM_CHAT_ID` / `TELEGRAM_ALLOWED_IDS` |
| Cloud | Cloudflare Worker `har-cloud`, D1 `har-db` (APAC); quản lý bằng `wrangler` trong `cloud/` |

## Kiểm tra nhanh

1. Telegram: `/trangthai` (đang làm gì, online, cảnh báo gần nhất) và `/homnay`.
2. Dashboard: góc trên phải "Cập nhật mỗi 2 s"; trang Tổng quan "Online".
3. Pi:

```bash
systemctl is-active har-ingest har-infer har-uplink har-notify har-bot mosquitto chrony
journalctl -u har-infer -n 30 --no-pager         # model đã nạp, cảnh báo, lệnh gửi bộ đeo
journalctl -u har-uplink -n 20 --no-pager        # "Đã gửi N bản ghi"; lỗi kết nối cloud
sudo systemctl restart har-infer                 # sau khi đổi model hoặc .env
```

Log không ghi token Telegram (`bot<token-ẩn>`) và không ghi từng request HTTP.

## Bộ đeo

- Bật bộ đeo: đặt yên trên bàn ~2 s để con quay tự hiệu chỉnh, rồi mới đeo.
- **Đổi người đeo hoặc cách đeo:** nhấn nút 3 lần rồi đứng thẳng yên (bíp dài = đạt), hoặc gõ `/hieuchinh` trên Telegram. Kết quả và nút "Khôi phục hướng cũ" gửi về Telegram.
- Nạp firmware (cắm USB): `cd firmware && pio run -e esp32dev -t upload`. Test logic trên máy tính: `pio test -e native`.
- Còi không kêu khi té:
  - Đang ở chế độ thu dữ liệu (màn hình `REC`): cảnh báo chỉ dùng LED và OLED, tối đa 15 phút sau lệnh thu cuối.
  - Bộ đeo offline: Pi vẫn báo Telegram sau 15 s (`reason = device_no_response`), nhưng không bật được còi.

## Model trên Pi

Model nằm ở `~/har/edge/models/current/` (`meta.json` + `model.joblib`). Bản cũ để cạnh: `rf-imu+baro-2.5s-v1`, `-v2`, `-v3`.

```bash
# quay lại model cũ (ví dụ v3)
cd ~/har/edge/models && rm -rf current && cp -a rf-imu+baro-2.5s-v3 current && sudo systemctl restart har-infer
# đưa model mới từ laptop (ml/models/<tên>) lên
scp ml/models/<tên>/meta.json ml/models/<tên>/model.joblib pi@192.168.12.19:har/edge/models/current/
```

Chỉnh không cần sửa code (`~/har/edge/.env`, rồi khởi động lại `har-infer`):

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `FALL_P_MODEL_ONLY` | 0,5 | P(té) để model tự nhờ bộ đeo báo động (khi ngưỡng bộ đeo không kích hoạt) |
| `FALL_P_CONFIRM` | 0,5 | P(té) để cảnh báo của bộ đeo thành mức cao |
| `STAIRS_MIN_ALT_M` | 0,3 | Bỏ nhãn cầu thang khi độ cao đổi ít hơn mức này trong 10 s (0 = tắt) |
| `STATUS_EVERY_S` | 5 | Chu kỳ gửi trạng thái (hoạt động đổi thì gửi ngay) |

## Cloud (Cloudflare)

Chạy trong thư mục `cloud/` trên laptop đã `npx wrangler login`.

```bash
npm run deploy                                                        # web app hoặc Worker đổi
node scripts/admin.mjs create-user --email a@b.com --role viewer --remote   # tài khoản mới (in mật khẩu 1 lần)
node scripts/admin.mjs list --remote
node scripts/admin.mjs rotate-key --dev har01 --remote               # lộ khóa thiết bị
npx wrangler d1 export har-db --remote --output ../har-db-$(date +%F).sql   # sao lưu D1
npx wrangler tail                                                     # xem log Worker trực tiếp
```

Cloud tự báo Telegram **"Pi mất kết nối"** khi Pi im quá 10 phút (tắt, mất điện, mất Internet) và báo khi Pi kết nối lại; Pi gửi nhịp tim mỗi 60 s kể cả khi bộ đeo tắt. Đổi token Telegram thì cũng chạy lại 2 lệnh `wrangler secret put TELEGRAM_*` trong [`cloud/README.md`](../cloud/README.md).

Sau `rotate-key`: sửa `VPS_DEVICE_KEY` trong `~/har/edge/.env` trên Pi, rồi `sudo systemctl restart har-uplink`.

Đẩy kết quả thí nghiệm lên trang Đánh giá model: chép `ml/results/<thí nghiệm>/metrics.json` lên Pi, gửi bằng `HttpPublisher.publish_metrics` (khóa thiết bị chỉ nằm trên Pi), hoặc `python ml/push_metrics.py` trên máy có khóa trong `edge/.env`.

## Mạng Wi-Fi: nhà và hotspot iPhone

Bộ đeo và Pi phải ở **cùng một mạng**. Bộ đeo lưu tối đa 3 mạng (`WIFI_SSID`, `WIFI_SSID_2`, `WIFI_SSID_3` trong `secrets.h`) và chọn theo **thứ tự ưu tiên**, không theo sóng mạnh nhất; Pi lưu nhiều mạng bằng NetworkManager với **cùng thứ tự** (`autoconnect-priority`), nên khi cả hai mạng cùng có sóng thì hai bên vào cùng một mạng.

| Ưu tiên | Mạng | Pi | Địa chỉ Pi trong `secrets.h` |
| --- | --- | --- | --- |
| 1 | Wi-Fi nhà `BIGHOME 02` | DHCP (đặt giữ IP `192.168.12.19` trên router), priority 10 | `MQTT_HOST` |
| 2 | Hotspot iPhone | IP cố định `172.20.10.14/28`, priority 5 | `MQTT_HOST_2 "172.20.10.14"` |

Pi còn lưu mạng khác (priority 0). Bộ đeo không biết các mạng đó, nên ở đó bộ đeo không nối được Pi.

**Trên iPhone** (Cài đặt → Điểm truy cập cá nhân):

1. Bật **Tối đa hóa tương thích**: hotspot phát 2,4 GHz. ESP32 không vào được 5 GHz.
2. Tên hotspot là tên iPhone (Cài đặt → Cài đặt chung → Giới thiệu → Tên). Đổi tên thì đổi cả trên Pi và trong `secrets.h`.
3. Để màn hình Điểm truy cập cá nhân mở khi bật Pi và bộ đeo; hotspot tự tắt khi không có thiết bị nào nối một lúc.

**Bộ đeo:** thêm vào `firmware/include/secrets.h` rồi nạp lại firmware:

```c
#define WIFI_SSID_2     "<tên iPhone>"
#define WIFI_PASSWORD_2 "<mật khẩu hotspot>"
#define MQTT_HOST_2     "172.20.10.14"
```

**Pi** (đã làm 22/11/2026; mạng hotspot đã lưu sẵn trên Pi):

```bash
sudo nmcli con mod "<tên iPhone>" ipv4.method manual ipv4.addresses 172.20.10.14/28   ipv4.gateway 172.20.10.1 ipv4.dns "172.20.10.1 1.1.1.1" connection.autoconnect-priority 5
sudo nmcli con mod "BIGHOME 02" connection.autoconnect-priority 10
sudo ufw allow from 172.20.10.0/28 to any port 1883 proto tcp comment "MQTT iPhone"
sudo ufw allow from 172.20.10.0/28 to any port 123 proto udp comment "NTP iPhone"
echo "allow 172.20.10.0/28" | sudo tee -a /etc/chrony/conf.d/har.conf && sudo systemctl restart chrony
```

Thêm một mạng mới cho Pi: gõ trực tiếp trên Pi `sudo nmcli dev wifi connect "<tên>" password "<mật khẩu>"`, không dán mật khẩu vào chat. Mạng mới có dải địa chỉ khác thì mở thêm dải đó trong `ufw` (cổng 1883, 123) và `/etc/chrony/conf.d/har.conf`; thiếu chrony thì bộ đeo không lấy được giờ (`ntp=0`) và không gửi dữ liệu.

**Lưu ý:**

- Đang ở mạng nào thì cả hai giữ mạng đó, kể cả khi mạng ưu tiên hơn xuất hiện. Về nhà mà vẫn bật hotspot thì hệ thống vẫn chạy trên hotspot (Internet qua 4G). Tắt hotspot: Pi tự sang Wi-Fi nhà, bộ đeo quét lại sau 20 s.
- Pi đang ở mạng khác mà bộ đeo đã vào hotspot: hai bên không thấy nhau. Ép Pi sang hotspot bằng `sudo nmcli con up "<tên iPhone>"` (mất SSH nếu laptop không cùng mạng) hoặc tắt rồi bật lại Pi khi chỉ có hotspot.
- `172.20.10.14` nằm trong dải iPhone cấp (`.2`–`.14`). iPhone cấp từ số nhỏ lên, nên chỉ trùng khi có rất nhiều thiết bị cùng nối.
- Kiểm tra: OLED dòng hai `WiFi: <tên iPhone>`; Serial `[wifi] vào mạng 2/2: …`, `[net] broker … -> 172.20.10.14`, `ntp=1`.

## Telegram

- Đổi token (lộ token): @BotFather `/revoke` → điền token mới vào `TELEGRAM_BOT_TOKEN` trong `.env` (giữ nguyên `TELEGRAM_CHAT_ID`) → `sudo systemctl restart har-notify har-bot` → cập nhật bí mật `TELEGRAM_BOT_TOKEN` của Worker (cảnh báo Pi mất kết nối).
- **Thêm người nhận cảnh báo** (mỗi người nhận tin riêng):
  1. Người mới mở `@harnoti_bot`, bấm **Start** (Telegram không cho bot nhắn người chưa bấm Start), rồi gửi `/trangthai`. Bot chưa trả lời vì người này chưa được phép.
  2. Trên Pi lấy chat ID của họ: `journalctl -u har-bot -n 50 | grep "không được phép"` (dòng `Bỏ lệnh từ chat không được phép <chat ID>`).
  3. Thêm vào `TELEGRAM_CHAT_ID` trong `~/har/edge/.env`, ngăn bằng dấu phẩy: `TELEGRAM_CHAT_ID=<người cũ>,<người mới>`, rồi `sudo systemctl restart har-notify har-bot`.
  4. Cập nhật bí mật của Worker cho tin "Pi mất kết nối": `cd cloud && npx wrangler secret put TELEGRAM_CHAT_ID`, dán cùng danh sách.
  5. Mọi người trong danh sách nhận cảnh báo, bấm được nút dưới tin và ra lệnh được. Người chặn bot hoặc sai chat ID bị bỏ qua (ghi log), không làm kẹt tin của người khác; lỗi mạng thì chỉ gửi lại cho người chưa nhận.
- Thêm nhóm người thân: thêm bot vào nhóm, gửi `/start@harnoti_bot`, lấy `chat.id` (số âm) từ `getUpdates`, đặt vào `TELEGRAM_CHAT_ID` (hoặc thêm vào `TELEGRAM_ALLOWED_IDS` để nhóm cũng ra lệnh được).
- Telegram trả `502` hoặc hết thời gian chờ (lỗi phía máy chủ Telegram): bot tự kết nối lại; lệnh gửi trong lúc lỗi mà cũ hơn 2 phút bị bỏ (gõ lại); cảnh báo không mất, `har-notify` gửi khi Telegram ổn và ghi "gửi trễ".

## Thu dữ liệu

- Telegram: `/thu <người> <nhãn> [ghi chú]` (vd `/thu T01 stairs_up vitri=A`), nút Dừng / Lượt nữa / Đổi chiều; `/dung`.
- Hoặc trên Pi: `cd ~/har/edge && .venv/bin/python record.py --subject S01 --activity walk --duration 60 --no-upright-cal`.
- Dữ liệu thử (T01…) không chép vào `ml/data/raw`: `ml/data/test/` chỉ để chấm điểm.

## Sự cố thường gặp

### Không vào được Pi

Pi không có RTC và nhật ký mặc định nằm trong RAM: sau khi Pi tắt (`sudo poweroff` hay mất điện), `journalctl --list-boots` chỉ thấy lần khởi động hiện tại, mốc đầu tiên là giờ lưu lần cuối trước khi tắt. Tắt Pi đúng cách: `sudo poweroff`, chờ đèn ACT tắt hẳn rồi mới rút điện.

`ping 192.168.12.19` không trả lời và dashboard "offline": kiểm tra Pi còn điện (đèn đỏ PWR), đèn ACT nháy; rút điện cắm lại. Mọi dịch vụ tự chạy khi khởi động. Bộ đeo vẫn tự kêu còi khi té (ngưỡng trên bộ đeo), nhưng không có Telegram và dashboard cho tới khi Pi chạy lại.

### DNS chậm

Router cấp cho Pi DNS đầu tiên `192.168.102.1` (không dùng được), nên mỗi lần phân giải tên chờ thêm ~5 s. **Đã sửa ngày 21/11** cho kết nối "BIGHOME 02" (5,03 s → 0,01 s). Nếu cài lại Pi hoặc đổi Wi-Fi, chạy lại:

```bash
nmcli -t -f NAME,DEVICE con show --active                         # tên kết nối, vd "BIGHOME 02"
sudo nmcli con mod "BIGHOME 02" ipv4.ignore-auto-dns yes ipv4.dns "192.168.12.1 1.1.1.1"
sudo nmcli device reapply wlan0 && cat /etc/resolv.conf
```

Hoặc bỏ `192.168.102.1` trong cài đặt DHCP của router.

### Dashboard đứng yên

- Góc trên phải ghi "Mất kết nối cloud": mạng của máy đang xem.
- "Online" nhưng không đổi: xem `journalctl -u har-uplink` trên Pi.
- Pi ghi "Uplink chạy với backend=console": `.env` thiếu `CLOUD_BACKEND=vps`.

### Nhận sai đứng / cầu thang

Thường do đổi người hoặc cách đeo mà chưa hiệu chỉnh: nhấn nút 3 lần (đứng thẳng yên). Phòng có áp suất dao động mạnh (cửa, quạt) có thể làm lọt nhãn "cầu thang" khi đứng; tăng `STAIRS_MIN_ALT_M` nếu cần (đổi lại nhận cầu thang kém hơn).
