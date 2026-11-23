# API cloud

Cloud đang dùng là Cloudflare Worker ([`cloud/`](../cloud/)), giữ đúng hợp đồng dưới đây của backend VPS ([`backend/`](../backend/), Swagger ở `https://<tên miền>/api/docs`). Khác biệt của Worker ghi ở cột "Việc làm" và [cuối file](#khác-biệt-của-cloudflare-worker).

| Phương thức và đường dẫn | Ai gọi | Xác thực | Việc làm |
| --- | --- | --- | --- |
| `POST /api/ingest/status` | Pi | `X-Device-Key` | Ghi đè trạng thái hiện tại, ghi lịch sử thưa (≤ 1 dòng/phút), phát qua WebSocket |
| `POST /api/ingest/segments` | Pi | `X-Device-Key` | `{"segments":[...]}` thêm theo lô; bỏ qua bản ghi trùng (`dev`+`start`) |
| `POST /api/ingest/events` | Pi | `X-Device-Key` | `{"events":[...]}`; cùng `id` thì cập nhật (giữ cờ "đã xử lý"), phát qua WebSocket |
| `POST /api/ingest/metrics` | Pi / laptop huấn luyện | `X-Device-Key` | Thêm hoặc ghi đè kết quả một thí nghiệm (`metrics.json`) |
| `POST /api/ingest/system_metrics` | Pi | `X-Device-Key` | `{"items":[...]}` độ trễ từng chặng, tỉ lệ mất gói, thời lượng pin theo ngày |
| `POST /api/ingest/heartbeat` | Pi | `X-Device-Key` | Chỉ Worker. `{"v":1,"t":...}` mỗi 60 s, cập nhật `devices.pi_seen_at` (cảnh báo "Pi mất kết nối") |
| `POST /api/auth/login` | Web app | — | `{"email","password"}` → JWT, hết hạn sau 12 giờ |
| `GET /api/auth/me` | Web app | JWT | Tài khoản đang đăng nhập |
| `GET /api/devices` | Web app | JWT | Danh sách thiết bị (không kèm băm key) |
| `GET /api/status` | Web app | JWT | Trạng thái hiện tại; `online=false` nếu cũ hơn 30 s |
| `GET /api/status/history?dev=&from=&to=` | Web app | JWT | Lịch sử ≤ 1 dòng/phút: pin, nhiệt độ, độ ẩm và số liệu cảm biến 1 phút (`svm_mean`, `svm_max`, `gyro_mean`, `p_hpa`) cho trang Cảm biến |
| `GET /api/sensors?dev=&since=` | Web app | JWT | Chỉ Worker. Biểu đồ trực tiếp: điểm 5 Hz trong 2 phút gần nhất mới hơn `since` (epoch ms): `{"imu": [[t, svm, svm_max, gyro]], "baro": [[t, p_pa]]}` |
| `GET /api/segments?dev=&from=&to=` | Web app | JWT | Đoạn hoạt động giao với khoảng thời gian (tối đa 8 ngày) |
| `GET /api/summary?dev=&day=&days=` | Web app | JWT | Tổng hợp theo ngày; `days=7` để so sánh 7 ngày |
| `GET /api/live?limit=` | Web app | JWT | Chỉ Worker. `{"status":[...], "events":[...]}` trong một request; dashboard hỏi mỗi 2 s |
| `GET /api/events?dev=&from=&to=&limit=` | Web app | JWT | Danh sách cảnh báo, mới nhất trước |
| `PATCH /api/events/{id}` | Web app | JWT | `{"acknowledged":true}` đánh dấu đã xử lý. `wearer_ack_at` (người đeo bấm nút sau khi té đã xác nhận) chỉ là thông tin, không làm cảnh báo thành đã xử lý |
| `GET /api/metrics` | Web app | JWT | `{"experiments":[...], "system":[...], "running_models":{...}}` |
| `WS /ws?token=` | Web app | JWT | Đẩy `{"type":"status"|"event","data":{...}}`; client gửi `ping` → `{"type":"pong"}` |
| `GET /api/health` | Giám sát | — | API và DB còn sống |

- Thiếu/sai JWT hoặc API key → `401`. API key của thiết bị A ghi dữ liệu cho thiết bị B → `403`.
- Mọi đường `ingest` đều idempotent nên outbox trên Pi gửi lại bao nhiêu lần cũng không tạo bản ghi trùng.
- Thân request dùng đúng tên trường trong [data-schema.md](data-schema.md); thời gian là epoch ms UTC.

## Khác biệt của Cloudflare Worker

- Không có WebSocket (`/ws`): web app build với `VITE_REALTIME=polling`, hỏi `GET /api/live` mỗi 2 s, ngừng khi tab ẩn.
- Thêm `POST /api/ingest/heartbeat` và Cron `*/5 * * * *`: Pi im quá `PI_OFFLINE_MIN` (10) phút → ghi sự kiện `offline` (nguồn `cloud`) và gửi Telegram; Pi gửi lại → báo đã kết nối lại.
- `POST /api/ingest/status` nhận thêm (tùy chọn) `sensors` `{"imu": [[t, svm_tb, svm_đỉnh, con_quay_tb]], "baro": [[t, p_pa]]}` (điểm 5 Hz mới từ lần gửi trước, tối đa 200 mỗi loại) và số liệu 1 phút `svm_mean`, `svm_max`, `gyro_mean`, `p_hpa`. Worker nối `sensors` vào cửa sổ 2 phút trong bảng `sensor_live` và ghi số liệu 1 phút vào `status_log`.
- Mật khẩu băm PBKDF2 (Web Crypto) thay cho bcrypt; dữ liệu trong D1 (SQLite) với cùng bảng như [data-schema.md](data-schema.md), thêm cột `devices.pi_seen_at`, `devices.pi_offline_since`.
