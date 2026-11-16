// Hiệu chỉnh hướng "đứng thẳng" theo cách người đeo đeo bộ đeo — C++ thuần, test được trên máy tính.
//
// Mỗi người đeo có thể cài hộp lệch (nghiêng 15–30°, đeo ngược...). Khi người đeo ĐỨNG THẲNG, YÊN,
// trung bình gia tốc trong một cửa sổ chính là hướng trọng lực của tư thế đứng → dùng làm vector "đứng
// thẳng" (đơn vị, theo trục chip) cho bộ phát hiện té và cho Pi. Cửa sổ chỉ được nhận khi:
//   - SVM dao động (max - min) < max_svm_span_g và |con quay| trung bình < max_gyro_dps (đang yên)
//   - |gia tốc trung bình| trong [min_g, max_g] (không rơi/rung, gia tốc kế bình thường)
// Thư viện KHÔNG biết người đeo có thật sự đang đứng hay đang nằm yên — người gọi phải yêu cầu đứng
// thẳng (record.py đếm ngược) và kiểm tra góc lệch so với giá trị trước (record.py hỏi xác nhận).
#pragma once
#include <math.h>

struct UprightCalParams {
  int samples = 100;             // 2 s ở 50 Hz
  float max_svm_span_g = 0.08f;  // đứng yên vẫn lắc nhẹ; đi bộ ~0,5 g trở lên
  float max_gyro_dps = 15.0f;    // trung bình |con quay| (đã trừ bias)
  float min_g = 0.85f;
  float max_g = 1.15f;
};

class UprightCal {
 public:
  enum Result { PENDING, OK, MOVING, BAD_GRAVITY };

  UprightCalParams& params() { return p_; }
  void start() {
    active_ = true;
    reset();
  }
  void stop() { active_ = false; }
  bool active() const { return active_; }

  // Gia tốc (g) và con quay (°/s) đã trừ bias. Trả kết quả khi đủ một cửa sổ.
  Result feed(float ax, float ay, float az, float gx, float gy, float gz) {
    if (!active_) return PENDING;
    const float svm = sqrtf(ax * ax + ay * ay + az * az);
    if (n_ == 0 || svm < svmMin_) svmMin_ = svm;
    if (n_ == 0 || svm > svmMax_) svmMax_ = svm;
    sum_[0] += ax;
    sum_[1] += ay;
    sum_[2] += az;
    gsum_ += sqrtf(gx * gx + gy * gy + gz * gz);
    if (++n_ < p_.samples) return PENDING;

    const float m[3] = {(float)(sum_[0] / n_), (float)(sum_[1] / n_), (float)(sum_[2] / n_)};
    const float norm = sqrtf(m[0] * m[0] + m[1] * m[1] + m[2] * m[2]);
    Result r = OK;
    if (svmMax_ - svmMin_ > p_.max_svm_span_g || gsum_ / n_ > p_.max_gyro_dps) r = MOVING;
    else if (norm < p_.min_g || norm > p_.max_g) r = BAD_GRAVITY;
    if (r == OK) {
      for (int k = 0; k < 3; k++) up_[k] = m[k] / norm;
      active_ = false;
    }
    reset();
    return r;
  }

  const float* up() const { return up_; }

  // Góc (độ) giữa hai vector bất kỳ khác 0
  static float angleDeg(const float a[3], const float b[3]) {
    const float na = sqrtf(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
    const float nb = sqrtf(b[0] * b[0] + b[1] * b[1] + b[2] * b[2]);
    if (na < 1e-6f || nb < 1e-6f) return 0;
    float c = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb);
    if (c > 1) c = 1;
    if (c < -1) c = -1;
    return acosf(c) * 57.2957795f;
  }

 private:
  void reset() {
    n_ = 0;
    sum_[0] = sum_[1] = sum_[2] = 0;
    gsum_ = 0;
  }

  UprightCalParams p_;
  bool active_ = false;
  int n_ = 0;
  double sum_[3] = {0, 0, 0};
  double gsum_ = 0;
  float svmMin_ = 0, svmMax_ = 0;
  float up_[3] = {-1, 0, 0};
};
