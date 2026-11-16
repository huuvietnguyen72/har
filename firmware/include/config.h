// Hằng số cấu hình firmware. Ngưỡng té mặc định nằm trong lib/fall_detector/fall_detector.h
// và có thể đổi lúc chạy bằng lệnh MQTT {"cmd":"set_threshold", ...} (lưu NVS).
#pragma once

#define FW_VERSION "1.0.0"

// --- Lấy mẫu ---
#define SAMPLE_PERIOD_MS 20     // 50 Hz
#define PACKET_SAMPLES 25       // 0,5 s mỗi gói IMU
#define ENV_EVERY_SAMPLES 5     // BMP280 mỗi 100 ms (10 Hz)
#define ENV_PACKET_SAMPLES 5    // 0,5 s mỗi gói env
#define SLOW_PERIOD_MS 10000    // AHT20 + áp pin mỗi 10 s

// MPU6050: ±8 g → 4096 LSB/g ; ±500 °/s → 65,5 LSB/(°/s). Khớp edge/har_edge/units.py
#define ACC_LSB_PER_G 4096.0f
#define GYRO_LSB_PER_DPS 65.5f
// Hệ trục = trục chip MPU6050 như đang hàn trên mạch: đeo hông phải, đứng thẳng thì trục X chỉ xuống
// đất (ax ≈ -1 g; phiên đi bộ 17/11: ax ≈ -0,97 g). Bộ phát hiện té (FallParams::up_*) và Pi
// (edge/har_edge/features.py UPRIGHT) dùng cùng quy ước này.
// Hiệu chỉnh độ lệch con quay (lib/gyro_cal): mỗi lần thử 1,5 s nằm yên, thử tối đa N lần sau khi
// khởi động hoặc sau lệnh {"cmd":"calibrate_gyro"}; không đạt thì giữ giá trị lưu NVS lần trước.
#define GYRO_CAL_TRIES 40       // 40 × 1,5 s = 60 s
// Hiệu chỉnh hướng đứng thẳng (lib/upright_cal) theo lệnh {"cmd":"calibrate_upright","id":...}:
// người đeo đứng thẳng yên; mỗi lần thử 2 s, tối đa N lần. Kết quả lưu NVS, gửi trong status.
#define UPRIGHT_CAL_TRIES 4     // 4 × 2 s = 8 s

// --- Mạng ---
#define MQTT_BUFFER_SIZE 2048   // mặc định 256 B của PubSubClient sẽ làm rơi gói IMU
#define RING_PACKETS 120        // vòng đệm 60 s khi mất kết nối (120 gói × 0,5 s)
#define REPLAY_AGE_MS 2000      // gói cũ hơn mức này khi gửi -> replay = true
#define MAX_PUBLISH_PER_LOOP 8
#define STATUS_PERIOD_MS 10000
#define NTP_SYNC_MS 60000       // hỏi giờ Pi mỗi 60 s (mặc định ESP-IDF 1 giờ; tối thiểu 15 s)
#define EVENT_RESEND_MS 5000    // gửi lại sự kiện đến khi Pi trả har/{dev}/ack
#define MAX_STORED_EVENTS 50

// --- Cảnh báo, nút ---
#define CANCEL_WINDOW_MS 10000  // thời gian người đeo được nhấn hủy
#define CONFIRMED_BUZZ_MS 30000 // còi kêu liên tục sau khi xác nhận
#define LONG_PRESS_MS 3000      // giữ 3 s = SOS
#define DOUBLE_PRESS_MS 400

// --- Pin ---
#define LOW_BATTERY_V 3.4f
#define BATTERY_DIVIDER 2.0f    // cầu chia 100k/100k
#define BATTERY_CAL 1.000f      // hệ số hiệu chỉnh theo đồng hồ đo (giai đoạn 1)
#define BATTERY_PRESENT_V 2.5f  // đo dưới mức này = không có cầu chia áp/pin -> battery_v = null, OLED hiện giờ

// --- Ngoại vi tùy chọn ---
#define BUZZER_PASSIVE 0        // 1 nếu dùng còi thụ động (cần phát tần số)
#define BUZZER_FREQ_HZ 2700
#define USE_VIBRATION 0         // 1 nếu có motor rung ở GPIO33
#define USE_OLED 1
#define DISPLAY_TIMEOUT_MS 0     // 0 = luôn sáng; >0 = tắt sau N ms không nhấn nút (tiết kiệm pin)
#define DISPLAY_DIM_MS 60000     // giảm sáng sau N ms không nhấn nút (0 = không giảm)
#define DISPLAY_REFRESH_MS 500  // ≤ 2 lần/giây
