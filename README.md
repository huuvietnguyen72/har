# HAR – Bộ đeo hông nhận dạng hoạt động và phát hiện té ngã

Đồ án IoT: bộ đeo hông nhận dạng 8 hoạt động và phát hiện té ngã cho người cao tuổi (prototype giám sát trong nhà).
Model chạy trên Raspberry Pi 4 (edge); kết quả, số liệu đánh giá và dashboard nằm trên VPS (cloud), không xem bằng localhost.

## Kiến trúc (IoT Level 5)

```
ESP32 + MPU6050 + BMP280 + OLED  --MQTT/Wi-Fi-->  Raspberry Pi 4  --HTTPS-->  VPS (FastAPI + PostgreSQL + Caddy)
   ngưỡng té, còi, nút hủy                       Mosquitto, ingest,           web app React (4 trang, đăng nhập)
                                                 infer, uplink, notify  --> Telegram
```

## Cấu trúc thư mục

| Thư mục | Nội dung |
| --- | --- |
| [`firmware/`](firmware/) | Firmware ESP32 (PlatformIO, Arduino framework) |
| [`edge/`](edge/) | Dịch vụ trên Pi 4: `har-ingest`, `har-infer`, `har-uplink`, `har-notify`, script thu dữ liệu |
| [`ml/`](ml/) | Xử lý dataset, huấn luyện Random Forest và 1D-CNN, xuất `metrics.json` |
| [`backend/`](backend/) | API FastAPI + PostgreSQL + Caddy, chạy bằng Docker Compose trên VPS |
| [`webapp/`](webapp/) | Web app React + Vite + TypeScript |
| [`hardware/`](hardware/) | Sơ đồ lắp mạch, bảng chân, ảnh mạch và hộp |
| [`docs/`](docs/) | Hợp đồng dữ liệu giữa các phần: MQTT, schema cloud, API, nhãn |

Đọc [`docs/`](docs/) trước khi viết code ở bất kỳ phần nào: đó là "hợp đồng" giữa firmware, Pi, backend và web app.

## Quy tắc chung

- **Không commit bí mật.** Mỗi phần có file mẫu (`.env.example`, `secrets.example.h`); copy thành file thật rồi điền. File thật đã nằm trong `.gitignore`.
- **Không commit dữ liệu thô hay model lớn.** Dataset để ở Google Drive của nhóm; repo chỉ chứa code và file `metrics.json`.
- Đổi schema trong `docs/` thì tăng số phiên bản `v` trong payload và ghi lại thay đổi ở cuối file đó.
- Mỗi việc một nhánh, gộp vào `main` qua pull request.

## Kế hoạch

Kế hoạch chi tiết theo giai đoạn nằm ở tài liệu kế hoạch của nhóm (6 giai đoạn: phần cứng → firmware → edge → dataset/model → suy luận thời gian thực → VPS + web app).
