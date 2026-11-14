# HAR – Bộ đeo hông nhận dạng hoạt động và phát hiện té ngã

Đồ án IoT: bộ đeo hông nhận dạng 8 hoạt động và phát hiện té ngã cho người cao tuổi (prototype giám sát trong nhà).
Model chạy trên Raspberry Pi 4 (edge); kết quả, số liệu đánh giá và dashboard nằm trên VPS (cloud), không xem bằng localhost.

## Kiến trúc (IoT Level 5)

```
ESP32 + MPU6050 + BMP280 + AHT20 + OLED ──MQTT/Wi-Fi──► Raspberry Pi 4 ──HTTPS──► VPS: Caddy + FastAPI + PostgreSQL
  ngưỡng té, còi, nút hủy, vòng đệm 60 s               Mosquitto, chrony            web app React (4 trang, đăng nhập)
                                                       har-ingest, har-infer,
                                                       har-uplink (outbox) ───────► (cùng VPS)
                                                       har-notify ────────────────► Telegram
```

## Cấu trúc thư mục

| Thư mục | Nội dung | Trạng thái |
| --- | --- | --- |
| [`firmware/`](firmware/) | Firmware ESP32 (PlatformIO, FreeRTOS 5 task) | Biên dịch được; 6 test native cho bộ phát hiện té và nút |
| [`edge/`](edge/) | Dịch vụ Pi: `har-ingest`, `har-infer`, `har-uplink`, `har-notify`; `record.py`, `replay.py`, `fake_device.py`; systemd, `setup-pi.sh` | 17 test pytest |
| [`ml/`](ml/) | Dataset, Random Forest, 1D-CNN (TFLite int8), thí nghiệm A1/A2/B1/B2/C/D, đẩy `metrics.json` | Chạy hết trên dữ liệu giả lập |
| [`backend/`](backend/) | FastAPI + PostgreSQL + Caddy, Docker Compose, Alembic, sao lưu, hướng dẫn dựng VPS | 9 test pytest |
| [`webapp/`](webapp/) | React + Vite + TypeScript: Tổng quan, Lịch sử, Cảnh báo, Đánh giá model | Build sạch; chạy thử với API thật |
| [`hardware/`](hardware/) | Sơ đồ lắp mạch, bảng chân, ảnh mạch và hộp | |
| [`docs/`](docs/) | Hợp đồng dữ liệu: MQTT, schema cloud, API, nhãn, bảng chân | |

Đọc [`docs/`](docs/) trước khi sửa code ở bất kỳ phần nào: đó là "hợp đồng" giữa firmware, Pi, backend và web app.

## Chạy thử toàn tuyến trên laptop (không cần phần cứng)

1. Backend: xem [`backend/README.md`](backend/README.md) (SQLite, không cần Docker) → tạo tài khoản và API key thiết bị.
2. Broker MQTT trên laptop (Mosquitto hoặc Docker `eclipse-mosquitto`).
3. Edge: `CLOUD_BACKEND=vps`, `VPS_API_URL=http://localhost:8000/api`, chạy 4 dịch vụ rồi `python fake_device.py` ([`edge/README.md`](edge/README.md)).
4. Web app: `VITE_DATA_SOURCE=api npm run dev` ([`webapp/README.md`](webapp/README.md)).

## Thứ tự triển khai thật

1. Lắp mạch, chỉnh MT3608 về 5,0 V **trước** khi nối ESP32 ([`hardware/`](hardware/)).
2. Nạp firmware ([`firmware/README.md`](firmware/README.md)).
3. Cài Pi: `sudo HOTSPOT_PASS=... bash edge/deploy/setup-pi.sh` ([`edge/README.md`](edge/README.md)).
4. Dựng VPS: [`backend/DEPLOY.md`](backend/DEPLOY.md).
5. Thu dataset bằng `record.py`, huấn luyện ở `ml/`, chép model sang `edge/models/current/`, đẩy `metrics.json` lên VPS.

## Quy tắc chung

- **Không commit bí mật.** Mỗi phần có file mẫu (`.env.example`, `secrets.example.h`); copy thành file thật rồi điền. File thật đã nằm trong `.gitignore`. Repo nên để **riêng tư**.
- **Không commit dữ liệu thô hay model lớn.** Dataset để ở Google Drive của nhóm; repo chỉ chứa code và file `metrics.json` của dữ liệu thật.
- Đổi schema trong `docs/` thì tăng số phiên bản `v` trong payload và ghi lại thay đổi ở cuối file đó.
- Mỗi việc một nhánh, gộp vào `main` qua pull request.
