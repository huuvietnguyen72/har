# 5. Deploy lên Cloudflare

Một **Cloudflare Worker** (`har-cloud`) phục vụ cả API `/api/*` lẫn dashboard React; dữ liệu nằm trong **D1** (`har-db`, SQLite của Cloudflare). Pi đẩy kết quả lên qua HTTPS; người xem mở dashboard bằng trình duyệt. Tài liệu kỹ thuật: [`../../cloud/README.md`](../../cloud/README.md), API: [`../api.md`](../api.md).

## 5.1. Vì sao chọn Cloudflare thay VPS

| | VPS (FastAPI + PostgreSQL, `backend/`) | Cloudflare Worker + D1 (`cloud/`) |
| --- | --- | --- |
| Chi phí | Thuê máy theo tháng | Gói miễn phí đủ cho 1 bộ đeo |
| Quản trị | Tự cài, cập nhật bảo mật, HTTPS, sao lưu | Không có máy chủ để quản trị, HTTPS sẵn |
| Hạn chế | VPS được đề nghị chạy Ubuntu 18.04, quá cũ cho Docker/Python hiện tại | Không có WebSocket (dashboard hỏi định kỳ), giới hạn request và CPU mỗi request |

Worker giữ **đúng hợp đồng API** của bản VPS, nên Pi chỉ đổi URL và web app không phải viết lại. Bản VPS giữ trong repo làm dự phòng.

## 5.2. Chuẩn bị

- Tài khoản Cloudflare (gói Free).
- Node.js ≥ 18 trên laptop.
- Repo đã clone; chạy mọi lệnh trong thư mục `cloud/`.

```bash
cd cloud
npm install
npx wrangler login         # mở trình duyệt, đăng nhập Cloudflare, bấm Allow
npx wrangler whoami        # kiểm tra đã đăng nhập
```

Lệnh giống nhau trên PowerShell và Git Bash, trừ chỗ có `$(...)`, `sed`, `tr` (chỉ chạy trong Git Bash hoặc trên Pi).

## 5.3. Deploy lần đầu

```bash
npx wrangler d1 create har-db --location apac       # in database_id
```

Chép `database_id` vào `cloud/wrangler.toml` (mục `[[d1_databases]]`). Repo đang ghi id của D1 nhóm; dựng hệ thống mới thì thay bằng id của mình.

```bash
npm run db:migrate                                   # tạo bảng trên D1 (migrations/0001, 0002)
node -e "process.stdout.write(require('crypto').randomBytes(32).toString('hex'))" | npx wrangler secret put JWT_SECRET
npm run deploy                                       # build webapp (--mode cloudflare) + deploy Worker
```

`npm run deploy` in ra:

```
Uploaded har-cloud
  https://har-cloud.<tên-tài-khoản>.workers.dev
  schedule: */5 * * * *          ← Cron kiểm tra Pi mất kết nối
```

Thiếu dòng `schedule` thì xem lại mục `[triggers]` trong `wrangler.toml`.

### Bí mật Telegram (cảnh báo "Pi mất kết nối")

Worker nhắn Telegram khi Pi im quá 10 phút, dùng cùng bot với `har-notify`. Chép thẳng từ `.env` trên Pi để token không hiện ra màn hình (Git Bash):

```bash
ssh pi@192.168.12.19 "sed -n 's/^TELEGRAM_BOT_TOKEN=//p' ~/har/edge/.env" | tr -d ' \r\n' | npx wrangler secret put TELEGRAM_BOT_TOKEN
ssh pi@192.168.12.19 "sed -n 's/^TELEGRAM_CHAT_ID=//p' ~/har/edge/.env" | tr -d ' \r\n' | npx wrangler secret put TELEGRAM_CHAT_ID
npx wrangler secret list                             # chỉ hiện tên: JWT_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

### Tài khoản dashboard và khóa thiết bị

Dashboard không có trang tự đăng ký; quản trị tạo tài khoản:

```bash
npm run admin -- create-user --email ban@example.com --role admin --remote     # in mật khẩu ngẫu nhiên MỘT lần
npm run admin -- create-user --email gv@example.com --role viewer --remote     # tài khoản chỉ xem (giảng viên)
npm run admin -- create-device --dev har01 --alias "Người đeo" --remote        # in khóa thiết bị MỘT lần
npm run admin -- list --remote
```

Muốn tự đặt mật khẩu thay vì mật khẩu ngẫu nhiên: thêm `--password '...'`. Mật khẩu và khóa thiết bị in ra chỉ một lần: lưu vào trình quản lý mật khẩu, không dán vào chat nhóm.

## 5.4. Nối Pi lên cloud

Trên Pi, `nano ~/har/edge/.env`:

```
CLOUD_BACKEND=vps
VPS_API_URL=https://har-cloud.<tên-tài-khoản>.workers.dev/api
VPS_DEVICE_KEY=<khóa thiết bị vừa in>
```

```bash
sudo systemctl restart har-uplink
journalctl -u har-uplink -n 20 --no-pager      # "Uplink chạy với backend=vps", "Đã gửi N bản ghi"
```

Tên biến còn chữ `VPS_` vì giữ tương thích với bản VPS; với Cloudflare vẫn dùng đúng các biến này.

## 5.5. Kiểm tra

| Kiểm tra | Đạt khi |
| --- | --- |
| Đăng nhập dashboard | Vào được bằng tài khoản vừa tạo |
| Trang Tổng quan | "Online", hoạt động hiện tại đổi theo người đeo trong ~2 s; góc trên "Cập nhật mỗi 2 s" |
| Cảnh báo té | Té lên nệm, không hủy → hộp đỏ giữa màn hình có âm báo; bấm "Đã xử lý" |
| Nhịp tim Pi | `npx wrangler d1 execute har-db --remote --command "SELECT dev, pi_seen_at FROM devices"`: `pi_seen_at` mới trong 60 s |
| Trang Đánh giá model | Có A1, A2, C, D sau khi `push_metrics.py` ([bước 4](04-du-lieu-huan-luyen-kiem-thu.md#47-đẩy-kết-quả-lên-dashboard)) |
| Log Worker | `npx wrangler tail` khi đang dùng dashboard, không có lỗi 5xx |

Độ trễ đo được: Pi → cloud trung vị ~0,6 s, chậm nhất 1,9 s.

## 5.6. Chạy thử trên máy

Thử Worker trên laptop trước khi deploy (D1 giả lập cục bộ):

```bash
echo "JWT_SECRET=$(node -e "process.stdout.write(require('crypto').randomBytes(32).toString('hex'))")" > .dev.vars
npm run build:web && npm run db:migrate:local
npm run admin -- create-user --email test@har.local --role admin --password matkhau-thu-123 --local
npm run admin -- create-device --dev har01 --local           # ghi lại khóa
npx wrangler dev --local --port 8787                         # http://127.0.0.1:8787
```

Cửa sổ khác, chạy 10 test đầu-cuối (dùng đúng `HttpPublisher` của Pi):

```bash
CLOUD_DEVICE_KEY=<khóa> CLOUD_EMAIL=test@har.local CLOUD_PASSWORD=matkhau-thu-123 \
  ../edge/.venv/Scripts/python -m pytest -q test/test_e2e.py
npm run typecheck
```

Thử Cron: chạy Worker với `--test-scheduled --var PI_OFFLINE_MIN:0.05` và đặt thêm `CLOUD_TEST_SCHEDULED=1` khi chạy pytest. `.dev.vars` chứa bí mật, nằm trong `.gitignore`.

## 5.7. Cập nhật, sao lưu

```bash
npm run deploy                                     # code Worker hoặc web app đổi
npm run db:migrate                                 # khi có file mới trong migrations/
npm run admin -- rotate-key --dev har01 --remote   # lộ khóa thiết bị: khóa mới → sửa .env trên Pi → restart har-uplink
npx wrangler d1 export har-db --remote --output ../har-db-$(date +%F).sql    # sao lưu D1 (không commit file này)
```

Đổi token Telegram (lộ token): sửa `.env` trên Pi, restart `har-notify har-bot`, rồi chạy lại 2 lệnh `wrangler secret put TELEGRAM_*` ở trên.

## Sự cố đã gặp

| Sự cố | Nguyên nhân | Xử lý |
| --- | --- | --- |
| Dashboard cập nhật chậm, cảnh báo té không nổi bật | Ban đầu hỏi lại mỗi 5 s; Pi mở kết nối HTTPS mới mỗi lần gửi | Dashboard hỏi `/api/live` (trạng thái + cảnh báo trong **một** request) mỗi 2 s, ngừng khi tab ẩn; Pi giữ kết nối HTTP 60 s; thêm hộp cảnh báo đỏ giữa màn hình kèm âm báo |
| Không có WebSocket trên Worker | Bản Worker không giữ kết nối lâu | Build web app với `VITE_REALTIME=polling` (`webapp/.env.cloudflare`); `/ws` trả 426 |
| Gửi lên cloud chậm ~5 s | DNS trên Pi (router cấp DNS hỏng) | Sửa DNS trên Pi ([bước 3](03-cai-dat-pi.md#32-ip-cố-định-và-dns)) |
| `admin.mjs ... --remote` lỗi đọc JSON | Wrangler in dòng tiến trình trước JSON; lệnh `--file` chỉ trả thống kê | Tách đọc (`--command --json`, bỏ dòng trước `[`) và ghi (`--file`); gọi wrangler bằng `node`, không qua shell |
| Gọi `/__scheduled` (thử Cron) trả về trang web | Phần phục vụ web app (SPA) nuốt đường dẫn này | Thêm `/__scheduled` vào `run_worker_first` trong `wrangler.toml` |
| Test Cron đọc DB trước khi Worker ghi xong | `ctx.waitUntil` chạy nền | Đổi thành `await` trong `scheduled()` |
| Test đầu-cuối chạy lần 2 thì lỗi | D1 cục bộ còn dữ liệu lần trước | Test lọc theo thời điểm bắt đầu của lần chạy |
| Bấm "Đã xử lý" trên trang Cảnh báo, dòng như "đổi loại" | Dòng vừa xử lý biến mất, dòng khác trượt lên chỗ đó (dữ liệu trên cloud vẫn đúng) | Dòng vừa xử lý ở lại 3 s; tab "Chưa xử lý" chỉ gồm té/SOS; thêm "Xử lý tất cả" |
| Dashboard "Offline" + Telegram "Pi mất kết nối" | Pi tắt (`sudo poweroff`), mất điện hoặc mất Internet | Đúng thiết kế. Cảnh báo sau 10–15 phút, báo lại khi Pi lên |
| `.dev.vars`, token suýt lọt vào commit | Dán thử chuỗi giống token thật vào test | Test chỉ dùng token giả; bí mật chỉ nằm trong `wrangler secret`, `.dev.vars`, `.env` |

**Giới hạn gói miễn phí** (kiểm tra lại trang giá Cloudflare): số request Worker mỗi ngày, ~10 ms CPU mỗi request (vì vậy PBKDF2 20.000 vòng), dung lượng và số dòng đọc/ghi D1 mỗi ngày. Một bộ đeo + vài tab dashboard dùng ít; đừng để nhiều tab dashboard mở cả ngày. Theo dõi mức dùng trên trang quản trị Cloudflare.
