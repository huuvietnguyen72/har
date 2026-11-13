# API backend (VPS)

Tài liệu tự sinh có ở `https://<tên miền>/docs` khi backend chạy.

| Phương thức và đường dẫn | Ai gọi | Xác thực | Việc làm |
| --- | --- | --- | --- |
| `POST /api/ingest/status` | Pi | `X-Device-Key` | Ghi đè trạng thái hiện tại, phát qua WebSocket |
| `POST /api/ingest/segments` | Pi | `X-Device-Key` | Thêm theo lô; bỏ qua bản ghi trùng |
| `POST /api/ingest/events` | Pi | `X-Device-Key` | Thêm sự kiện, phát qua WebSocket |
| `POST /api/ingest/metrics` | Pi / laptop huấn luyện | `X-Device-Key` | Thêm hoặc ghi đè kết quả một thí nghiệm |
| `POST /api/auth/login` | Web app | — | Trả JWT, hết hạn sau 12 giờ |
| `GET /api/status` | Web app | JWT | Trạng thái hiện tại của các thiết bị |
| `GET /api/segments?dev=&from=&to=` | Web app | JWT | Đoạn hoạt động trong khoảng thời gian |
| `GET /api/summary?dev=&day=` | Web app | JWT | Tổng hợp theo ngày |
| `GET /api/events?dev=&from=&to=` | Web app | JWT | Danh sách cảnh báo |
| `PATCH /api/events/{id}` | Web app | JWT | Đánh dấu đã xử lý (`acknowledged`) |
| `GET /api/metrics` | Web app | JWT | Kết quả các thí nghiệm model |
| `WS /ws?token=` | Web app | JWT | Đẩy `status` và `event` mới |
| `GET /api/health` | Giám sát | — | API và DB còn sống |

Lỗi xác thực trả `401`. Thân request của các đường `ingest` dùng đúng trường trong [data-schema.md](data-schema.md).
