// Hiệu chỉnh độ lệch (bias) con quay MPU6050 — C++ thuần, test được trên máy tính (pio test -e native).
//
// Con quay MEMS đọc khác 0 khi nằm yên (đo trên mạch: gx ≈ +13,8 °/s). Lấy trung bình một cửa sổ
// `samples` mẫu thô khi thiết bị nằm yên rồi trừ đi ở mọi mẫu sau đó. Cửa sổ chỉ được chấp nhận khi:
//   - độ lệch chuẩn từng trục con quay < max_std_dps (đo lúc nằm yên thật: 0,05–0,2 °/s)
//   - độ biến thiên SVM gia tốc < max_acc_span_g (không bị cầm, lắc)
//   - |trung bình| từng trục < max_bias_dps (lớn hơn là đang quay đều, không phải bias)
// Cửa sổ không đạt thì bỏ và thử cửa sổ kế tiếp; người gọi quyết định thử bao nhiêu lần.
#pragma once
#include <math.h>
#include <stdint.h>

struct GyroCalParams {
  int samples = 75;            // 1,5 s ở 50 Hz
  float lsb_per_dps = 65.5f;   // ±500 °/s
  float lsb_per_g = 4096.0f;   // ±8 g
  float max_std_dps = 1.0f;
  float max_acc_span_g = 0.03f;
  float max_bias_dps = 40.0f;
};

class GyroCal {
 public:
  enum Result { PENDING, OK, MOVING, OUT_OF_RANGE };

  GyroCalParams& params() { return p_; }

  // Bắt đầu đo (bias hiện tại vẫn giữ nguyên cho tới khi có cửa sổ đạt)
  void start() {
    active_ = true;
    resetWindow();
  }
  void stop() { active_ = false; }
  bool active() const { return active_; }

  // raw[0..5] = ax, ay, az, gx, gy, gz thô (CHƯA trừ bias). Trả kết quả khi đủ một cửa sổ.
  Result feed(const int16_t raw[6]) {
    if (!active_) return PENDING;
    const float svm = sqrtf((float)raw[0] * raw[0] + (float)raw[1] * raw[1] + (float)raw[2] * raw[2]) / p_.lsb_per_g;
    if (n_ == 0 || svm < accMin_) accMin_ = svm;
    if (n_ == 0 || svm > accMax_) accMax_ = svm;
    for (int k = 0; k < 3; k++) {
      const double v = raw[3 + k];
      sum_[k] += v;
      sq_[k] += v * v;
    }
    if (++n_ < p_.samples) return PENDING;

    Result r = OK;
    double mean[3];
    for (int k = 0; k < 3; k++) {
      mean[k] = sum_[k] / n_;
      const double var = sq_[k] / n_ - mean[k] * mean[k];
      const double stdDps = sqrt(var > 0 ? var : 0) / p_.lsb_per_dps;
      if (stdDps > p_.max_std_dps) r = MOVING;
      if (r == OK && fabs(mean[k]) / p_.lsb_per_dps > p_.max_bias_dps) r = OUT_OF_RANGE;
    }
    if (accMax_ - accMin_ > p_.max_acc_span_g) r = MOVING;
    if (r == OK) {
      for (int k = 0; k < 3; k++) bias_[k] = (int16_t)lround(mean[k]);
      active_ = false;
    }
    resetWindow();
    return r;
  }

  // Đặt bias có sẵn (ví dụ đọc từ NVS lúc khởi động)
  void setBias(int16_t bx, int16_t by, int16_t bz) {
    bias_[0] = bx;
    bias_[1] = by;
    bias_[2] = bz;
  }
  const int16_t* bias() const { return bias_; }
  float biasDps(int k) const { return bias_[k] / p_.lsb_per_dps; }

  // Trừ bias vào 3 trục con quay của raw (bão hòa trong int16)
  void apply(int16_t raw[6]) const {
    for (int k = 0; k < 3; k++) {
      int32_t v = (int32_t)raw[3 + k] - bias_[k];
      raw[3 + k] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
    }
  }

 private:
  void resetWindow() {
    n_ = 0;
    for (int k = 0; k < 3; k++) sum_[k] = sq_[k] = 0;
  }

  GyroCalParams p_;
  bool active_ = false;
  int n_ = 0;
  double sum_[3] = {0, 0, 0}, sq_[3] = {0, 0, 0};
  float accMin_ = 0, accMax_ = 0;
  int16_t bias_[3] = {0, 0, 0};
};
