# MQTT (Mosquitto trên Pi)

Broker chỉ nghe trên mạng hotspot của Pi, cổng 1883, bắt buộc user/mật khẩu.

| Topic | Hướng | QoS | Nội dung |
| --- | --- | --- | --- |
| `har/{dev}/imu` | ESP32 → Pi | 0 | Gói 25 mẫu IMU (0,5 s) |
| `har/{dev}/env` | ESP32 → Pi | 0 | 5 mẫu áp suất (0,5 s), kèm nhiệt độ/độ ẩm khi có |
| `har/{dev}/event` | ESP32 → Pi | 1 | `suspected`, `cancelled`, `confirmed`, `sos`, `marker` |
| `har/{dev}/status` | ESP32 → Pi | 1, retained | Pin, RSSI, uptime, firmware; Last Will = `offline` |
| `har/{dev}/cmd` | Pi → ESP32 | 1 | Bắt đầu/dừng thu, đổi ngưỡng, kêu còi thử |
| `har/{dev}/display` | Pi → ESP32 | 0, retained | Nhãn hiện tại và thông tin phiên thu cho OLED |
| `har/{dev}/pred` | `har-infer` → nội bộ Pi | 0 | Dự đoán mỗi 1 s |
| `har/{dev}/alert` | `har-infer` → `har-notify`, `har-uplink` | 1 | Cảnh báo đã hợp nhất |

## Payload (phiên bản `v: 1`)

```jsonc
// har/har01/imu — giá trị thô int16; Pi đổi sang g và °/s
// MPU6050: ±8 g (4096 LSB/g), ±500 °/s (65.5 LSB/(°/s))
{"v":1, "seq":10234, "t0":1763060000000, "dt":20, "replay":false,
 "ax":[/*25 số*/], "ay":[], "az":[], "gx":[], "gy":[], "gz":[]}

// har/har01/env
{"v":1, "seq":2047, "t0":1763060000000, "dt":100,
 "p_pa":[/*5 số*/], "temp_c":29.4, "rh":71.2}

// har/har01/event
{"v":1, "id":"har01-1763060012345", "type":"suspected", "t":1763060012345, "peak_g":3.4}

// har/har01/status (retained)
{"v":1, "t":1763060010000, "online":true, "battery_v":3.92, "rssi":-58, "uptime_s":3600, "fw":"0.1.0"}

// har/har01/pred
{"v":1, "t":1763060013000, "label":"walk", "conf":0.91,
 "probs":{"stand":0.02, "walk":0.91}, "model":"cnn-imu+baro-v3"}

// har/har01/display (retained)
{"v":1, "label":"walk", "conf":0.91, "mode":"monitor"}
```

- `seq` tăng 1 mỗi gói, để Pi đếm gói mất.
- `replay: true` khi ESP32 gửi bù dữ liệu đệm lúc mất kết nối.
- `id` của sự kiện do ESP32 tạo, dùng để chống trùng tới tận cơ sở dữ liệu trên VPS.

## Lịch sử thay đổi

- v1: bản đầu tiên.
