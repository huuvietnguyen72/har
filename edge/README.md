# Edge – Raspberry Pi 4

Raspberry Pi OS 64-bit (Bookworm), Python ≥ 3.11. Mỗi dịch vụ chạy bằng systemd. Kế hoạch: [`docs/ke-hoach.md`](../docs/ke-hoach.md).

```
ESP32 ──MQTT──► Mosquitto ──► har-ingest ─► data/raw, data/sessions, SQLite(device_events) ─► ack về ESP32
                     │
                     └──────► har-infer ──► har/{dev}/pred, har/{dev}/display (OLED)
                                   │        SQLite: predictions, alerts, outbox
                                   ▼
                     har-notify (alerts → Telegram)      har-uplink (outbox → VPS qua Publisher)
```

| Dịch vụ | Module | Việc làm |
| --- | --- | --- |
| Mosquitto | `deploy/mosquitto-har.conf` | Broker MQTT 1883, bắt buộc user/mật khẩu; tường lửa chỉ mở cho mạng nội bộ |
| chrony | `deploy/chrony-har.conf` | Máy chủ giờ cho ESP32 (vẫn chạy khi mất Internet) |
| `har-ingest` | `har_edge/ingest.py` | Đổi đơn vị, đếm gói mất theo `seq`, ghi CSV liên tục + theo phiên thu, xác nhận sự kiện (`har/{dev}/ack`) |
| `har-infer` | `har_edge/infer.py` | Cửa sổ 2,5 s mỗi 1 s, model (RF/TFLite/luật), làm mượt đa số 3, gộp đoạn, hợp nhất cảnh báo té, trạng thái mỗi 5 s |
| `har-uplink` | `har_edge/uplink.py` | Outbox SQLite → VPS (`HttpPublisher`) hoặc màn hình (`ConsolePublisher`), thử lại 2→60 s, ưu tiên sự kiện |
| `har-notify` | `har_edge/notify.py` | Telegram, chống gửi trùng, gộp < 60 s, đánh dấu "gửi trễ" |
| `har-bot` | `har_edge/bot.py` | Lệnh Telegram: `/trangthai`, `/homnay`, `/coi`, `/tatcoi`; nút dưới tin cảnh báo té |

Logic thuần (làm mượt, gộp đoạn, hợp nhất cảnh báo, cảnh báo kỹ thuật) nằm trong `har_edge/logic.py`; đặc trưng dùng chung với `ml/` nằm trong `har_edge/features.py`.

## Quy tắc hợp nhất cảnh báo té

| ESP32 (ngưỡng) | Model (±3 s quanh va chạm) | Kết luận |
| --- | --- | --- |
| `suspected` → `confirmed` (hoặc không có phản hồi sau 15 s) | P(té) ≥ `FALL_P_CONFIRM` | Té, mức **cao**, nguồn `both` |
| như trên | P(té) < `FALL_P_CONFIRM` | Vẫn cảnh báo, mức **trung bình**, nguồn `threshold` |
| không kích hoạt | P(té) ≥ `FALL_P_MODEL_ONLY` rồi nằm ≥ `FALL_LIE_AFTER_S` | Cảnh báo, mức **trung bình**, nguồn `model` |
| `cancelled` | bất kỳ | Chỉ ghi lại và đẩy lên cloud (`cancelled = true`), không gửi Telegram |
| `sos` | bất kỳ | Cảnh báo SOS ngay |

## Cài trên Pi

```bash
git clone https://github.com/huuvietnguyen72/har.git && cd har/edge
sudo HOTSPOT_PASS='matkhau-wifi' bash deploy/setup-pi.sh   # hotspot, Mosquitto, chrony, ufw, venv, systemd
nano .env                                                  # MQTT_PASSWORD, VPS_*, TELEGRAM_*
sudo systemctl restart har-ingest har-infer har-uplink har-notify har-bot
journalctl -fu har-infer
```

Mạng đang dùng: Pi (`raspivn`, 192.168.12.19) và ESP32 cùng vào Wi-Fi nhà, ESP32 tìm Pi qua `raspivn.local`. `setup-pi.sh` hiện chỉ có chế độ hotspot (`wlan0` phát Wi-Fi, tên máy `hargw`), nên Pi đang chạy được cài tay theo các bước của script, bỏ phần hotspot và đổi tên máy, mở tường lửa cho dải mạng nhà và 5353/udp (mDNS). Chi tiết: [`../docs/firmware-integration.md`](../docs/firmware-integration.md) mục 1.

## Bot Telegram

Tạo bot bằng @BotFather, điền `TELEGRAM_BOT_TOKEN` trong `.env`, bấm **Start** với bot (nhóm: gửi `/start@tên_bot`), rồi lấy `chat.id` từ `https://api.telegram.org/bot<token>/getUpdates` và điền `TELEGRAM_CHAT_ID`. `har-notify` gửi cảnh báo; `har-bot` nhận lệnh (long polling, không cần mở cổng):

| Lệnh | Việc |
| --- | --- |
| `/trangthai` | Đang làm gì, từ lúc nào, online không, cảnh báo gần nhất, Wi-Fi |
| `/homnay` | Thời gian từng hoạt động hôm nay (theo model), số cảnh báo té, té đã hủy, SOS, mất kết nối |
| `/coi [giây]` | Bật còi trên bộ đeo (mặc định 3 s, tối đa 10 s) |
| `/tatcoi` | Tắt còi sau khi té đã xác nhận |
| Nút **Tắt còi**, **Đã kiểm tra, ổn** | Gắn dưới tin cảnh báo té và SOS |

- Chỉ nhận lệnh từ `TELEGRAM_CHAT_ID` và `TELEGRAM_ALLOWED_IDS`. Lệnh gửi lúc bot đang tắt mà cũ hơn 2 phút thì bỏ qua.
- **Không tắt còi trong 10 s chờ hủy:** firmware coi `cancel_alarm` lúc đó là người đeo tự hủy, nên cú ngã sẽ không được báo. Trong 10 s đó chỉ người đeo được hủy bằng nút.
- Mọi thao tác ghi vào bảng `bot_actions` (ai, lúc nào, việc gì).

## Chạy và thử trên laptop (không cần ESP32)

Cần một broker MQTT (Mosquitto cài sẵn, hoặc `docker run -p 1883:1883 eclipse-mosquitto:2 mosquitto -c /mosquitto-no-auth.conf`).

```bash
cd edge
python -m venv .venv && .venv/Scripts/activate     # Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                               # MQTT_HOST=localhost, MQTT_USER để trống
pytest -q                                          # unit test, không cần broker

# mỗi lệnh một cửa sổ terminal
python -m har_edge.ingest
python -m har_edge.infer
python -m har_edge.uplink        # CLOUD_BACKEND=console in ra màn hình; =vps gửi lên VPS
python -m har_edge.notify
python fake_device.py --script "walk:20,sit:15,fall:8,lie:10"
```

## Thu dữ liệu và phát lại

```bash
python record.py --subject S01 --activity walk --duration 180   # ghi data/sessions/<id>/
python replay.py data/sessions/<id> --speed 2                    # phát lại lên MQTT để thử toàn tuyến
python rebuild_sessions.py --all --dry-run                       # cắt lại phiên từ data/raw theo thời điểm đo
```

Mỗi phiên có `imu.csv` (t, ax, ay, az [g], gx, gy, gz [°/s]), `env.csv` (t, p_pa), `events.csv` (mốc `marker` khi nhấn đúp nút) và `meta.json` (người, nhãn, số gói, số gói mất, số mẫu, vector đứng thẳng). Mẫu thuộc phiên theo thời điểm đo (`start ≤ t ≤ end`); sau lệnh dừng `har-ingest` chờ 90 s nhận gói tới trễ (kể cả gửi bù sau khi mất kết nối) rồi mới đóng phiên. Chép thư mục `data/sessions/` (không chép `data/sessions_backup/`) sang `ml/data/raw/` để huấn luyện.

## Đưa model mới lên Pi

`ml/` xuất thư mục model (`meta.json` + `model.joblib` hoặc `.tflite`). Chép vào `edge/models/current/` rồi `sudo systemctl restart har-infer`. Không có model thì `har-infer` dùng luật đơn giản (`HeuristicModel`) để chạy thử toàn tuyến.
