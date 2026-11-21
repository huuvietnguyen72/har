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

Sau `rotate-key`: sửa `VPS_DEVICE_KEY` trong `~/har/edge/.env` trên Pi, rồi `sudo systemctl restart har-uplink`.

Đẩy kết quả thí nghiệm lên trang Đánh giá model: chép `ml/results/<thí nghiệm>/metrics.json` lên Pi, gửi bằng `HttpPublisher.publish_metrics` (khóa thiết bị chỉ nằm trên Pi), hoặc `python ml/push_metrics.py` trên máy có khóa trong `edge/.env`.

## Telegram

- Đổi token (lộ token): @BotFather `/revoke` → điền token mới vào `TELEGRAM_BOT_TOKEN` trong `.env` (giữ nguyên `TELEGRAM_CHAT_ID`) → `sudo systemctl restart har-notify har-bot`.
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
