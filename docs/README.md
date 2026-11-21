# Tài liệu dùng chung

| File | Nội dung |
| --- | --- |
| [huong-dan/](huong-dan/README.md) | **Hướng dẫn cho thành viên nhóm**: lắp mạch, nạp firmware, cài Pi, huấn luyện và kiểm thử, deploy Cloudflare, kèm sự cố đã gặp |
| [kien-truc.md](kien-truc.md) | **Cấu trúc hệ thống**: 3 tầng, dịch vụ, luồng dữ liệu, luồng cảnh báo té, bảo mật |
| [ke-hoach.md](ke-hoach.md) | Kế hoạch dự án: hệ thống hiện có, việc tiếp theo, chỉ số đánh giá |
| [labels.md](labels.md) | 8 mã nhãn hoạt động, dùng giống nhau ở mọi nơi |
| [mqtt.md](mqtt.md) | Topic và payload MQTT giữa ESP32 và Pi |
| [data-schema.md](data-schema.md) | Bảng dữ liệu trên cloud (D1 trên Cloudflare dùng cùng bảng với bản VPS PostgreSQL) |
| [api.md](api.md) | API cloud (Cloudflare Worker giữ đúng hợp đồng của backend VPS, thêm `/api/live`, `/api/ingest/heartbeat`) |
| [pinout.md](pinout.md) | Bảng chân ESP32 theo mạch thật |
| [van-hanh.md](van-hanh.md) | Vận hành hằng ngày, sự cố thường gặp |
| [firmware-integration.md](firmware-integration.md) | Nhật ký tích hợp firmware với Pi: vấn đề gặp, cách sửa, số đo kiểm chứng |

Phần cứng bộ đeo (sơ đồ mạch, cấu trúc hộp): [`../hardware/README.md`](../hardware/README.md).

Quy ước chung: thời gian là epoch mili giây UTC; `{dev}` là mã thiết bị, ví dụ `har01`.
