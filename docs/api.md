# API backend (VPS)

Tài liệu tự sinh (Swagger) có ở `https://<tên miền>/api/docs` khi backend chạy.

| Phương thức và đường dẫn | Ai gọi | Xác thực | Việc làm |
| --- | --- | --- | --- |
| `POST /api/ingest/status` | Pi | `X-Device-Key` | Ghi đè trạng thái hiện tại, ghi lịch sử thưa (≤ 1 dòng/phút), phát qua WebSocket |
| `POST /api/ingest/segments` | Pi | `X-Device-Key` | `{"segments":[...]}` thêm theo lô; bỏ qua bản ghi trùng (`dev`+`start`) |
| `POST /api/ingest/events` | Pi | `X-Device-Key` | `{"events":[...]}`; cùng `id` thì cập nhật (giữ cờ "đã xử lý"), phát qua WebSocket |
| `POST /api/ingest/metrics` | Pi / laptop huấn luyện | `X-Device-Key` | Thêm hoặc ghi đè kết quả một thí nghiệm (`metrics.json`) |
| `POST /api/ingest/system_metrics` | Pi | `X-Device-Key` | `{"items":[...]}` độ trễ từng chặng, tỉ lệ mất gói, thời lượng pin theo ngày |
| `POST /api/auth/login` | Web app | — | `{"email","password"}` → JWT, hết hạn sau 12 giờ |
| `GET /api/auth/me` | Web app | JWT | Tài khoản đang đăng nhập |
| `GET /api/devices` | Web app | JWT | Danh sách thiết bị (không kèm băm key) |
| `GET /api/status` | Web app | JWT | Trạng thái hiện tại; `online=false` nếu cũ hơn 30 s |
| `GET /api/status/history?dev=&from=&to=` | Web app | JWT | Lịch sử pin, nhiệt độ, độ ẩm (đồ thị pin) |
| `GET /api/segments?dev=&from=&to=` | Web app | JWT | Đoạn hoạt động giao với khoảng thời gian (tối đa 8 ngày) |
| `GET /api/summary?dev=&day=&days=` | Web app | JWT | Tổng hợp theo ngày; `days=7` để so sánh 7 ngày |
| `GET /api/events?dev=&from=&to=&limit=` | Web app | JWT | Danh sách cảnh báo, mới nhất trước |
| `PATCH /api/events/{id}` | Web app | JWT | `{"acknowledged":true}` đánh dấu đã xử lý |
| `GET /api/metrics` | Web app | JWT | `{"experiments":[...], "system":[...], "running_models":{...}}` |
| `WS /ws?token=` | Web app | JWT | Đẩy `{"type":"status"|"event","data":{...}}`; client gửi `ping` → `{"type":"pong"}` |
| `GET /api/health` | Giám sát | — | API và DB còn sống |

- Thiếu/sai JWT hoặc API key → `401`. API key của thiết bị A ghi dữ liệu cho thiết bị B → `403`.
- Mọi đường `ingest` đều idempotent nên outbox trên Pi gửi lại bao nhiêu lần cũng không tạo bản ghi trùng.
- Thân request dùng đúng tên trường trong [data-schema.md](data-schema.md); thời gian là epoch ms UTC.
