// Phát hiện té bằng ngưỡng — C++ thuần, không phụ thuộc Arduino (test được bằng `pio test -e native`).
// Giữ GIỐNG HỆT bản Python edge/har_edge/fall_threshold.py (dùng cho thí nghiệm D).
//
// 1. Rơi tự do : SVM < freefall_g kéo dài ≥ freefall_ms
// 2. Va chạm   : trong impact_window_ms sau đó có SVM > impact_g
// 3. Bất động  : trong 1 s cuối của still_delay_ms sau va chạm, SVM ∈ [still_lo, still_hi],
//                con quay < still_gyro_dps (≥ still_ratio số mẫu) và tư thế đã đổi (nghiêng > posture_deg)
// 4. → nghi té (update() trả true, đọc impactMs() và peakG())
#pragma once
#include <stdint.h>

struct FallParams {
  float freefall_g = 0.4f;
  uint32_t freefall_ms = 80;
  float impact_g = 2.5f;
  uint32_t impact_window_ms = 500;
  uint32_t still_delay_ms = 2000;
  uint32_t still_check_ms = 1000;
  float still_lo = 0.8f;
  float still_hi = 1.2f;
  float still_gyro_dps = 30.0f;
  float still_ratio = 0.9f;
  float posture_deg = 50.0f;
  // Hướng "đứng thẳng" trong hệ trục cảm biến: đeo hông phải, mũi tên Y chỉ xuống đất → ay ≈ -1 g
  float up_x = 0.0f, up_y = -1.0f, up_z = 0.0f;
};

class FallDetector {
 public:
  enum State : uint8_t { IDLE, FREEFALL, IMPACT };

  explicit FallDetector(const FallParams& p = FallParams()) : p_(p) {}

  // Gọi cho từng mẫu 50 Hz. ax..az theo g, gx..gz theo °/s, t tính bằng ms.
  bool update(uint64_t t, float ax, float ay, float az, float gx, float gy, float gz);

  void reset() { state_ = IDLE; ffActive_ = false; }
  State state() const { return state_; }
  uint64_t impactMs() const { return lastImpact_; }
  float peakG() const { return lastPeak_; }
  float tiltDeg() const { return lastTilt_; }
  FallParams& params() { return p_; }

 private:
  FallParams p_;
  State state_ = IDLE;
  bool ffActive_ = false;
  uint64_t ffStart_ = 0, ffEnd_ = 0, impactT_ = 0;
  float peak_ = 0;
  uint32_t n_ = 0, nStill_ = 0;
  float sx_ = 0, sy_ = 0, sz_ = 0;
  uint64_t lastImpact_ = 0;
  float lastPeak_ = 0, lastTilt_ = 0;
};
