# 3. Cài đặt Raspberry Pi 4

Pi là tầng edge: broker MQTT, máy chủ giờ cho ESP32, lưu dữ liệu thô, chạy model, gửi Telegram và đẩy kết quả lên cloud. Chi tiết các dịch vụ: [`../../edge/README.md`](../../edge/README.md).

> **Đọc trước:** script `edge/deploy/setup-pi.sh` biến `wlan0` thành **hotspot** riêng và đổi tên máy thành `hargw`. Nếu Pi đang vào mạng bằng Wi-Fi (không có dây LAN), chạy script này sẽ làm **mất Internet và mất SSH**. Nhóm dùng phương án ESP32 và Pi cùng vào Wi-Fi nhà, nên cài tay theo các bước dưới (giống script, bỏ phần hotspot, đổi dải mạng).

## 3.1. Ghi thẻ nhớ

Dùng **Raspberry Pi Imager**:

| Mục | Giá trị |
| --- | --- |
| Hệ điều hành | Raspberry Pi OS (64-bit), Bookworm |
| Hostname | `raspivn` |
| Người dùng | `pi` + mật khẩu riêng |
| Wi-Fi | Wi-Fi nhà, quốc gia `VN` |
| Dịch vụ | Bật SSH |

Cắm thẻ, bật Pi, chờ ~1 phút rồi từ laptop:

```bash
ssh pi@raspivn.local          # không được thì tìm IP Pi trên trang quản trị router: ssh pi@192.168.12.19
sudo apt update && sudo apt -y full-upgrade
```

## 3.2. IP cố định và DNS

- **IP cố định:** đặt DHCP reservation cho Pi trên router (nhóm dùng `192.168.12.19`). mDNS `raspivn.local` thỉnh thoảng không trả lời.
- **DNS:** router cấp DNS đầu tiên không dùng được, mỗi lần phân giải tên chờ ~5 s (gửi lên cloud chậm theo). Sửa:

```bash
nmcli -t -f NAME,DEVICE con show --active            # tên kết nối Wi-Fi, ví dụ "BIGHOME 02"
sudo nmcli con mod "BIGHOME 02" ipv4.ignore-auto-dns yes ipv4.dns "192.168.12.1 1.1.1.1"
sudo nmcli device reapply wlan0 && cat /etc/resolv.conf
```

## 3.3. Gói hệ thống và code

```bash
sudo apt -y install git mosquitto mosquitto-clients chrony python3-venv python3-dev avahi-daemon ufw
git clone https://github.com/huuvietnguyen72/har.git ~/har
```

Repo riêng tư thì cần đăng nhập GitHub trên Pi (`gh auth login` hoặc token).

## 3.4. Mosquitto

```bash
sudo install -m 644 ~/har/edge/deploy/mosquitto-har.conf /etc/mosquitto/conf.d/har.conf
sudo mosquitto_passwd -c /etc/mosquitto/passwd har01      # tài khoản cho ESP32
sudo mosquitto_passwd /etc/mosquitto/passwd har-edge      # tài khoản cho các dịch vụ Pi
sudo chown mosquitto: /etc/mosquitto/passwd && sudo chmod 600 /etc/mosquitto/passwd
sudo systemctl enable --now mosquitto && sudo systemctl restart mosquitto
```

Mật khẩu nên ngẫu nhiên ~20 ký tự. Mật khẩu `har01` điền vào `secrets.h` của firmware, mật khẩu `har-edge` điền vào `~/har/edge/.env`.

## 3.5. chrony (máy chủ giờ cho ESP32)

File mẫu trong repo ghi dải hotspot `10.42.0.0/24`; đổi sang dải mạng nhà:

```bash
sudo install -d /etc/chrony/conf.d
printf 'allow 192.168.12.0/24\nlocal stratum 10\n' | sudo tee /etc/chrony/conf.d/har.conf
grep -q "confdir /etc/chrony/conf.d" /etc/chrony/chrony.conf || echo "confdir /etc/chrony/conf.d" | sudo tee -a /etc/chrony/chrony.conf
sudo systemctl enable --now chrony && sudo systemctl restart chrony
```

`local stratum 10` giúp Pi vẫn phát giờ khi mất Internet.

## 3.6. Tường lửa

```bash
sudo ufw allow ssh
sudo ufw allow from 192.168.12.0/24 to any port 1883 proto tcp    # MQTT
sudo ufw allow from 192.168.12.0/24 to any port 123 proto udp     # NTP
sudo ufw allow 5353/udp                                           # mDNS (raspivn.local)
sudo ufw --force enable && sudo ufw status
```

Không mở cổng nào ra Internet: Pi tự gọi ra cloud và Telegram, không cần nhận kết nối từ ngoài.

## 3.7. Môi trường Python và cấu hình

```bash
cd ~/har/edge
python3 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env && nano .env
```

| Biến | Giá trị |
| --- | --- |
| `MQTT_HOST`, `MQTT_USER`, `MQTT_PASSWORD` | `localhost`, `har-edge`, mật khẩu ở bước 3.4 |
| `CLOUD_BACKEND` | `console` lúc mới cài (in ra màn hình); `vps` sau khi có cloud ([bước 5](05-deploy-cloudflare.md)) |
| `VPS_API_URL`, `VPS_DEVICE_KEY` | URL Worker `https://har-cloud.<tên>.workers.dev/api` và khóa thiết bị (bước 5) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Bước 3.9 |
| `FALL_P_MODEL_ONLY`, `FALL_P_CONFIRM` | `0.5` |
| `STAIRS_MIN_ALT_M` | `0.3` |

Sửa `.env` bằng `nano` trực tiếp trên Pi; không dán token, mật khẩu qua chat. `.env` không bao giờ commit.

## 3.8. Dịch vụ systemd

File dịch vụ mặc định cho người dùng `pi` và thư mục `/home/pi/har/edge`:

```bash
for s in ingest infer uplink notify bot; do sudo cp ~/har/edge/deploy/har-$s.service /etc/systemd/system/; done
sudo systemctl daemon-reload
sudo systemctl enable --now har-ingest har-infer har-uplink har-notify har-bot
systemctl is-active har-ingest har-infer har-uplink har-notify har-bot mosquitto chrony
journalctl -fu har-infer
```

Tên người dùng khác `pi` thì sửa `User=` và đường dẫn trong các file `.service` trước khi chép.

## 3.9. Bot Telegram

1. Trên Telegram, nhắn **@BotFather** → `/newbot` → lấy token, điền `TELEGRAM_BOT_TOKEN`.
2. Mở bot vừa tạo, bấm **Start** (nhóm: thêm bot vào nhóm, gửi `/start@tên_bot`).
3. Lấy chat ID: mở `https://api.telegram.org/bot<token>/getUpdates` trên trình duyệt của mình, tìm `"chat":{"id":...}` (nhóm là số âm), điền `TELEGRAM_CHAT_ID`.
4. `sudo systemctl restart har-notify har-bot`, gõ `/trangthai` để thử.

Danh sách lệnh: [`../../edge/README.md`](../../edge/README.md#bot-telegram).

## 3.10. Model

Không có model thì `har-infer` dùng luật đơn giản, chỉ để thử toàn tuyến. Chép model từ laptop ([bước 4](04-du-lieu-huan-luyen-kiem-thu.md#46-đưa-model-lên-pi)):

```bash
scp ml/models/<tên>/meta.json ml/models/<tên>/model.joblib pi@192.168.12.19:har/edge/models/current/
ssh pi@192.168.12.19 'sudo systemctl restart har-infer && journalctl -u har-infer -n 20 --no-pager'
```

Phiên bản **scikit-learn trên laptop và Pi phải giống nhau** (hiện 1.9.1), nếu không `model.joblib` có thể không nạp được hoặc cảnh báo khác phiên bản.

## 3.11. Cập nhật code về sau

```bash
cd ~/har && git pull --ff-only
sudo systemctl restart har-infer          # hoặc dịch vụ có code thay đổi
```

## 3.12. Kiểm tra

| Kiểm tra | Lệnh / đạt khi |
| --- | --- |
| 7 dịch vụ chạy | `systemctl is-active ...` toàn `active` |
| Bộ đeo nối được | `mosquitto_sub -u har-edge -P '...' -t 'har/har01/#' -v` thấy `imu`, `env`, `status` |
| ESP32 lấy giờ | `chronyc clients` có IP của ESP32 |
| Dữ liệu thô | `ls ~/har/edge/data/raw/har01/` có file theo ngày |
| Model chạy | `journalctl -u har-infer` có dòng nạp model và nhãn dự đoán |
| Telegram | `/trangthai` trả lời |
| Tự chạy khi khởi động | `sudo reboot`, 1–2 phút sau mọi dịch vụ `active`, bộ đeo tự nối lại |
| Test | `cd ~/har/edge && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q` (45 test) |

## Sự cố đã gặp

| Sự cố | Nguyên nhân | Xử lý |
| --- | --- | --- |
| `setup-pi.sh` có thể làm mất Internet và SSH | Script chỉ có chế độ hotspot trên `wlan0` | Cài tay như trên ([nhật ký mục 1](../firmware-integration.md#1-mạng-esp32-và-pi-cùng-vào-wi-fi-nhà)) |
| Dấu thời gian lệch 12 s sau khi Pi khởi động lại | Pi **không có RTC**, giờ lấy từ lần tắt trước tới khi chrony chỉnh | Firmware hỏi giờ mỗi 60 s. **Demo phải có Internet cho Pi** (hoặc gắn module RTC) ([mục 12](../firmware-integration.md#12-pi-sai-giờ-sau-khi-khởi-động-lại)) |
| Gửi lên cloud chậm ~5 s mỗi lần | DNS đầu tiên router cấp không dùng được | Sửa DNS (bước 3.2): 5,03 s → 0,01 s |
| `raspivn.local` lúc được lúc không | mDNS trên mạng nhà | Dùng IP cố định |
| Gói tới trễ lọt sang phiên thu sau | `har-ingest` từng gán gói theo lúc tới Pi | Gán theo thời điểm đo, chờ 90 s rồi mới đóng phiên; `rebuild_sessions.py` cắt lại phiên cũ ([mục 17](../firmware-integration.md#17-gói-tới-trễ-lọt-sang-phiên-sau)) |
| **Token Telegram lộ trong log** | Thư viện httpx ghi cả URL `.../bot<token>/...` vào journal | `har_edge/logutil` che token, tắt log từng request. Đã `/revoke` token cũ ở @BotFather và điền token mới. Lộ token: làm lại ngay như vậy |
| Bot không trả lời ~19 phút | Máy chủ Telegram trả `502` (lỗi phía Telegram) | Bot tự kết nối lại; cảnh báo không mất, gửi muộn kèm "gửi trễ"; lệnh cũ hơn 2 phút bị bỏ, gõ lại |
| Sau khi tắt Pi không xem được log cũ | Nhật ký systemd nằm trong RAM | Tùy chọn bật lưu vĩnh viễn: `sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald` |
| Dashboard "offline", Telegram báo mất kết nối | Thường do tắt Pi bằng `sudo poweroff` | Bình thường. Tắt Pi đúng cách: `sudo poweroff`, chờ đèn ACT tắt hẳn rồi rút điện; bật lại thì mọi dịch vụ tự chạy |
| Uplink ghi `backend=console`, không có gì lên cloud | `.env` thiếu `CLOUD_BACKEND=vps` | Sửa `.env`, `sudo systemctl restart har-uplink` |
| Từng mở trang tạm cổng 8080 để xem kết quả | Lúc chưa có cloud | Đã gỡ và đóng cổng tường lửa khi có dashboard Cloudflare; không cần mở lại |

Vận hành hằng ngày sau khi cài: [`../van-hanh.md`](../van-hanh.md).
