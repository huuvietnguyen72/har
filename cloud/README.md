# HAR cloud trên Cloudflare

Một **Cloudflare Worker** phục vụ cả API `/api/*` lẫn web app (dashboard), dữ liệu nằm trong **D1** (SQLite của Cloudflare). Kết quả nhận dạng, cảnh báo, metrics và dashboard đều nằm trên cloud; Pi chỉ đẩy dữ liệu lên.

```
Pi (har-uplink) ──HTTPS, X-Device-Key──► Worker /api/ingest/*  ──► D1 (har-db)
Trình duyệt ─────HTTPS, JWT────────────► Worker /api/*          ◄──┘
                                          + web app tĩnh (webapp/dist)
```

- Giữ **nguyên hợp đồng API** của bản VPS (`backend/api`): Pi chỉ đổi `VPS_API_URL`, web app giữ `VITE_API_URL=/api`.
- Không có WebSocket: web app build với `VITE_REALTIME=polling` (`webapp/.env.cloudflare`), hỏi lại mỗi 5 s.
- Tài khoản do quản trị tạo (không tự đăng ký); mật khẩu PBKDF2-SHA256; khóa thiết bị lưu dạng sha256.

| File | Nội dung |
| --- | --- |
| `src/index.ts` | Định tuyến, kiểm tra dữ liệu, ingest (Pi), đọc (web app), đăng nhập |
| `src/crypto.ts` | JWT HS256, PBKDF2, sha256 bằng Web Crypto (không thư viện ngoài) |
| `migrations/0001_init.sql` | 8 bảng, giống `backend/api/app/models.py` |
| `scripts/admin.mjs` | Tạo tài khoản, cấp và đổi khóa thiết bị (thay `python -m app.cli`) |
| `test/test_e2e.py` | Kiểm tra từ đầu tới cuối, dùng đúng `HttpPublisher` của Pi |

## Deploy lần đầu

Cần Node ≥ 18 và một tài khoản Cloudflare (gói miễn phí đủ dùng).

```bash
cd cloud
npm install
npx wrangler login                      # mở trình duyệt, bấm Allow
npx wrangler d1 create har-db           # chép database_id vào wrangler.toml
npm run db:migrate                      # tạo bảng trên D1
npm run deploy                          # build web app + deploy; in ra https://har-cloud.<tên>.workers.dev
node -e "process.stdout.write(require('crypto').randomBytes(32).toString('hex'))" | npx wrangler secret put JWT_SECRET
```

Cảnh báo "Pi mất kết nối" (Cron Trigger mỗi 5 phút, `checkPiOffline`): Pi (`har-uplink`) gửi nhịp tim `/api/ingest/heartbeat` mỗi 60 s, độc lập với bộ đeo. Pi im quá `PI_OFFLINE_MIN` (10 phút) → Worker nhắn Telegram một lần và ghi sự kiện `offline` (nguồn `cloud`); Pi gửi lại → nhắn "đã kết nối lại". Cần token và chat của cùng bot với `har-notify` (chép thẳng từ Pi, không hiện ra):

```bash
ssh pi@192.168.12.19 "sed -n 's/^TELEGRAM_BOT_TOKEN=//p' ~/har/edge/.env" | tr -d ' 
' | npx wrangler secret put TELEGRAM_BOT_TOKEN
ssh pi@192.168.12.19 "sed -n 's/^TELEGRAM_CHAT_ID=//p' ~/har/edge/.env" | tr -d ' 
' | npx wrangler secret put TELEGRAM_CHAT_ID
```

Tạo tài khoản đăng nhập và khóa cho bộ đeo:

```bash
npm run admin -- create-user --email ban@example.com --role admin --remote    # in mật khẩu ngẫu nhiên, chỉ 1 lần
npm run admin -- create-device --dev har01 --alias "Người đeo" --remote       # in API key, chỉ 1 lần
```

Trên Pi, sửa `~/har/edge/.env` rồi `sudo systemctl restart har-uplink`:

```
CLOUD_BACKEND=vps
VPS_API_URL=https://har-cloud.<tên>.workers.dev/api
VPS_DEVICE_KEY=<API key vừa in>
```

Đẩy kết quả thí nghiệm lên trang Đánh giá model: `cd ml && python push_metrics.py` (đọc `VPS_API_URL`, `VPS_DEVICE_KEY` từ `edge/.env`).

## Cập nhật

```bash
npm run deploy                          # code Worker hoặc web app đổi
npm run db:migrate                      # khi có file mới trong migrations/ (0002: nhịp tim Pi)
npm run admin -- rotate-key --dev har01 --remote   # lộ khóa thiết bị: cấp khóa mới, sửa .env trên Pi
```

## Chạy và kiểm tra trên máy

```bash
echo "JWT_SECRET=$(node -e "process.stdout.write(require('crypto').randomBytes(32).toString('hex'))")" > .dev.vars
npm run build:web && npm run db:migrate:local
npm run admin -- create-user --email test@har.local --role admin --password matkhau-thu-123 --local
npm run admin -- create-device --dev har01 --local                 # ghi lại API key
npx wrangler dev --local --port 8787                               # http://127.0.0.1:8787
# thử Cron: thêm --test-scheduled --var PI_OFFLINE_MIN:0.05 rồi CLOUD_TEST_SCHEDULED=1 khi chạy pytest
CLOUD_DEVICE_KEY=<key> CLOUD_EMAIL=test@har.local CLOUD_PASSWORD=matkhau-thu-123 \
  ../edge/.venv/Scripts/python -m pytest -q test/test_e2e.py
npm run typecheck
```

## Giới hạn gói miễn phí (kiểm tra lại trang giá của Cloudflare)

- Worker: số request mỗi ngày có hạn. File tĩnh của web app không đi qua Worker (`run_worker_first` chỉ gồm `/api/*`). Pi gửi trạng thái khoảng 5 s/lần, một tab dashboard mở hỏi 2 API mỗi 5 s.
- CPU mỗi request khoảng 10 ms: vì vậy PBKDF2 dùng 20 000 vòng (lưu kèm mỗi mật khẩu, tăng được sau).
- D1: dung lượng và số dòng đọc/ghi mỗi ngày có hạn; một bộ đeo dùng ít.
