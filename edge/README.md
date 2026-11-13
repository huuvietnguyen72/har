# Edge – Raspberry Pi 4

Raspberry Pi OS 64-bit (Bookworm), Python 3.11. Mỗi dịch vụ chạy bằng systemd. Thiết kế ở kế hoạch, giai đoạn 3 và 5.

| Dịch vụ | Việc làm |
| --- | --- |
| Mosquitto | Broker MQTT, chỉ nghe trên mạng hotspot, có user/mật khẩu |
| chrony | Máy chủ giờ cho ESP32 |
| `har-ingest` | Nhận gói thô, đổi đơn vị, kiểm tra `seq`, ghi file phiên thu |
| `har-infer` | Cửa sổ trượt 2,5 s mỗi 1 s, chạy model, hợp nhất cảnh báo té |
| `har-uplink` | Đẩy lên VPS qua lớp `Publisher` (`HttpPublisher`, `ConsolePublisher`), outbox SQLite |
| `har-notify` | Gửi Telegram, chống gửi trùng |

Script hỗ trợ: `record.py` (bắt đầu/dừng phiên thu có nhãn), `replay.py` (phát lại phiên thu lên MQTT để thử không cần thiết bị), `fake_device.py` (giả lập ESP32).

## Bắt đầu

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rồi điền
```
