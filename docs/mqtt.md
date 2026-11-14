# MQTT (Mosquitto trên Pi)

Broker cổng 1883, bắt buộc user/mật khẩu; tường lửa chỉ mở cho mạng hotspot (10.42.0.0/24).

| Topic | Hướng | QoS | Nội dung |
| --- | --- | --- | --- |
| `har/{dev}/imu` | ESP32 → Pi | 0 | Gói 25 mẫu IMU (0,5 s) |
| `har/{dev}/env` | ESP32 → Pi | 0 | 5 mẫu áp suất (0,5 s), kèm nhiệt độ/độ ẩm khi có số mới |
| `har/{dev}/event` | ESP32 → Pi | 0* | `suspected`, `cancelled`, `confirmed`, `sos`, `marker` |
| `har/{dev}/ack` | Pi (`har-ingest`) → ESP32 | 1 | Xác nhận đã lưu sự kiện; ESP32 xóa khỏi LittleFS |
| `har/{dev}/status` | ESP32 → Pi | 0, retained | Pin, RSSI, uptime, firmware; Last Will = `{"v":1,"online":false}` |
| `har/{dev}/cmd` | Pi → ESP32 | 1 | Lệnh (xem dưới) |
| `har/{dev}/display` | `har-infer` → ESP32 | 0, retained | Nhãn hiện tại cho OLED |
| `har/{dev}/session` | `record.py` → `har-ingest` | 1 | Bắt đầu/kết thúc phiên thu có nhãn |
| `har/{dev}/pred` | `har-infer` → nội bộ Pi | 0 | Dự đoán mỗi 1 s |
| `har/{dev}/alert` | `har-infer` → nội bộ Pi | 1 | Cảnh báo đã hợp nhất |

\* PubSubClient chỉ publish được QoS 0, nên độ tin cậy của sự kiện do tầng ứng dụng bảo đảm: ESP32 lưu mỗi sự kiện vào LittleFS và gửi lại mỗi 5 s cho đến khi nhận `har/{dev}/ack` có cùng `id`. Phía Pi chống trùng bằng `id` (SQLite và tới tận PostgreSQL trên VPS).

## Payload (phiên bản `v: 1`)

```jsonc
// har/har01/imu — giá trị thô int16; Pi đổi sang g và °/s
// MPU6050: ±8 g (4096 LSB/g), ±500 °/s (65,5 LSB/(°/s)); mẫu i có thời điểm t0 + i*dt
{"v":1, "seq":10234, "t0":1763060000000, "dt":20, "replay":false,
 "ax":[/*25 số*/], "ay":[], "az":[], "gx":[], "gy":[], "gz":[]}

// har/har01/env — p_pa theo Pa, 10 Hz
{"v":1, "seq":2047, "t0":1763060000000, "dt":100, "p_pa":[/*5 số*/], "temp_c":29.4, "rh":71.2}

// har/har01/event — t của suspected là thời điểm va chạm; cancelled/confirmed trỏ về suspected bằng "ref"
{"v":1, "id":"har01-1763060012345", "type":"suspected", "t":1763060012345, "peak_g":3.4}
{"v":1, "id":"har01-1763060024400", "type":"confirmed", "t":1763060024400, "ref":"har01-1763060012345", "peak_g":3.4}
{"v":1, "id":"har01-1763060100000", "type":"sos", "t":1763060100000}

// har/har01/ack
{"v":1, "id":"har01-1763060012345"}

// har/har01/status (retained)
{"v":1, "t":1763060010000, "online":true, "battery_v":3.92, "rssi":-58, "uptime_s":3600, "fw":"1.0.0",
 "heap":182000, "mpu_ok":true, "bmp_ok":true, "aht_ok":true, "pending_events":0, "dropped":0}

// har/har01/cmd
{"cmd":"beep", "ms":200}
{"cmd":"display", "mode":"record", "activity":"walk"}      // mode: monitor | record
{"cmd":"set_threshold", "freefall_g":0.4, "freefall_ms":80, "impact_g":2.5,
 "impact_window_ms":500, "still_gyro_dps":30, "posture_deg":50}   // lưu NVS
{"cmd":"test_alarm"}
{"cmd":"reboot"}

// har/har01/display (retained)
{"v":1, "label":"walk", "conf":0.91, "mode":"monitor"}

// har/har01/session
{"action":"start", "id":"har01_S01_walk_20261120-101500", "subject":"S01", "activity":"walk", "note":""}
{"action":"stop", "id":"har01_S01_walk_20261120-101500"}

// har/har01/pred
{"v":1, "t":1763060013000, "label":"walk", "raw":"walk", "conf":0.91,
 "probs":{"walk":0.91, "stairs_up":0.05, "stand":0.02}, "model":"rf-imu+baro-2.5s-v1"}
```

- `seq` tăng 1 mỗi gói (riêng cho imu và env), để Pi đếm gói mất.
- `replay: true` khi ESP32 gửi bù dữ liệu đệm lúc mất kết nối (vòng đệm 60 s); `har-infer` bỏ qua gói replay, `har-ingest` vẫn lưu.
- ESP32 chỉ gửi dữ liệu sau khi đồng bộ giờ NTP với Pi (chrony); trước đó vẫn chạy phát hiện té.

## Lịch sử thay đổi

- v1: bản đầu tiên. Khi hiện thực bổ sung (không đổi trường cũ): topic `ack` và `session`, trường `ref` của sự kiện, các trường chẩn đoán trong `status`, Last Will dạng JSON.
