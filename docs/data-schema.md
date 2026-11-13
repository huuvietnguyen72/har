# Dữ liệu trên VPS (PostgreSQL)

Dữ liệu thô 50 Hz **không** lên VPS; chỉ nằm trên Pi và trong dataset của nhóm.

| Bảng | Khóa | Trường chính |
| --- | --- | --- |
| `devices` | `dev` | bí danh người đeo, vị trí đeo, phiên bản firmware, model đang chạy, băm API key |
| `status` (1 dòng/thiết bị, ghi đè) | `dev` | `t`, `label`, `conf`, `online`, `battery_v`, `battery_pct`, `temp_c`, `rh`, `rssi` |
| `segments` | `dev` + `start` | `start`, `end`, `label`, `conf_avg` |
| `daily_summary` | `dev` + `day` | số giây mỗi nhãn, số cảnh báo, thời gian online |
| `events` | `id` | `dev`, `t`, `type`, `severity`, `source` (`threshold`/`model`/`both`), `prob`, `prev_label`, `cancelled`, `acknowledged`, `delivered_late` |
| `metrics` | `experiment` | `model`, `features`, `window_s`, `accuracy`, `macro_f1`, `f1_per_class` (JSON), `confusion` (JSON), `n_windows`, `n_subjects`, `created_at` |
| `system_metrics` | `dev` + `day` | độ trễ trung vị/p95 từng chặng, tỉ lệ mất gói, thời lượng pin đo được |
| `users` | `id` | `email`, `password_hash`, `role` |

Giá trị `type` của `events`: `fall`, `sos`, `low_battery`, `offline`. `severity`: `high`, `medium`, `info`.
