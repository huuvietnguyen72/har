# Dữ liệu trên VPS (PostgreSQL)

Dữ liệu thô 50 Hz **không** lên VPS; chỉ nằm trên Pi và trong dataset của nhóm. Định nghĩa bảng: [`backend/api/app/models.py`](../backend/api/app/models.py), migration: `backend/api/alembic/versions/`.

| Bảng | Khóa | Trường chính |
| --- | --- | --- |
| `devices` | `dev` | `alias` (bí danh người đeo), `position`, `fw`, `model` (model đang chạy), `key_hash` (sha256 API key) |
| `status` (1 dòng/thiết bị, ghi đè) | `dev` | `t`, `label`, `conf`, `online`, `battery_v`, `battery_pct`, `temp_c`, `rh`, `rssi`, `model`, `received_at` |
| `status_log` | `id` | `dev`, `t`, `online`, `battery_v`, `battery_pct`, `temp_c`, `rh` — tối đa 1 dòng/phút, cho đồ thị pin |
| `segments` | `dev` + `start` | `start`, `end`, `label`, `conf_avg` |
| `events` | `id` (từ thiết bị, chống trùng) | `dev`, `t`, `type`, `severity`, `source`, `prob`, `prev_label`, `battery_pct`, `cancelled`, `acknowledged`, `acknowledged_at`, `acknowledged_by`, `delivered_late`, `received_at` |
| `metrics` | `experiment` | `model`, `features`, `window_s`, `accuracy`, `macro_f1`, `f1_per_class` (JSON), `confusion` (JSON `{"labels","matrix"}`), `n_windows`, `n_subjects`, `extra` (JSON), `created_at` |
| `system_metrics` | `dev` + `day` | `latency` (JSON `{chặng: {median, p95, n}}`), `packet_loss` (0..1), `packets`, `battery_hours`, `extra` |
| `users` | `id` | `email`, `password_hash` (bcrypt), `role` (`admin`/`viewer`) |

- `daily_summary` (số giây mỗi nhãn, số cảnh báo, thời gian online theo ngày) được **tính khi đọc** từ `segments` và `events` (`GET /api/summary`), nên luôn khớp dữ liệu gốc; ngày chia theo `TZ_NAME` (mặc định Asia/Ho_Chi_Minh).
- `type` của `events`: `fall`, `sos`, `low_battery`, `offline`. `severity`: `high`, `medium`, `info`. `source`: `threshold`, `model`, `both`, `device`, `edge`.
- Chặng độ trễ trong `system_metrics.latency`: `device_pi` (mẫu cuối gói → Pi nhận), `infer` (thời gian chạy model), `sample_result` (mẫu cuối cửa sổ → có kết quả), `pi_cloud` (Pi tạo trạng thái → VPS nhận).
- `metrics.extra` của thí nghiệm D: `{"methods": {"threshold"|"model"|"combined": {"sensitivity", "false_alarms_per_hour", "specificity_recordings", "detect_delay_ms_median"}}, "adl_hours": ...}`. Kết quả từ dữ liệu giả lập có `"synthetic": true`.
