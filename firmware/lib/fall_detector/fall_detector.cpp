#include "fall_detector.h"

#include <math.h>

bool FallDetector::update(uint64_t t, float ax, float ay, float az, float gx, float gy, float gz) {
  const float svm = sqrtf(ax * ax + ay * ay + az * az);
  const float gmag = sqrtf(gx * gx + gy * gy + gz * gz);

  switch (state_) {
    case IDLE:
      if (svm < p_.freefall_g) {
        if (!ffActive_) {
          ffActive_ = true;
          ffStart_ = t;
        }
        if (t - ffStart_ >= p_.freefall_ms) {
          state_ = FREEFALL;
          ffEnd_ = 0;
        }
      } else {
        ffActive_ = false;
      }
      break;

    case FREEFALL: {
      if (svm < p_.freefall_g) {
        ffEnd_ = t;  // vẫn đang rơi
      } else if (svm > p_.impact_g) {
        state_ = IMPACT;
        impactT_ = t;
        peak_ = svm;
        n_ = nStill_ = 0;
        sx_ = sy_ = sz_ = 0;
      } else {
        const uint64_t ref = ffEnd_ > ffStart_ ? ffEnd_ : ffStart_;
        if (t - ref > p_.impact_window_ms) reset();
      }
      break;
    }

    case IMPACT: {
      const uint64_t dt = t - impactT_;
      if (dt < 300 && svm > peak_) peak_ = svm;
      if (dt >= p_.still_delay_ms - p_.still_check_ms) {
        n_++;
        if (svm >= p_.still_lo && svm <= p_.still_hi && gmag < p_.still_gyro_dps) nStill_++;
        sx_ += ax;
        sy_ += ay;
        sz_ += az;
      }
      if (dt >= p_.still_delay_ms) {
        const bool still = n_ > 0 && (float)nStill_ / (float)n_ >= p_.still_ratio;
        const float k = n_ ? 1.0f / n_ : 1.0f;
        const float mx = sx_ * k, my = sy_ * k, mz = sz_ * k;
        float norm = sqrtf(mx * mx + my * my + mz * mz);
        if (norm < 1e-6f) norm = 1.0f;
        float c = (mx * p_.up_x + my * p_.up_y + mz * p_.up_z) / norm;
        if (c > 1) c = 1;
        if (c < -1) c = -1;
        const float tilt = acosf(c) * 57.2957795f;
        lastImpact_ = impactT_;
        lastPeak_ = peak_;
        lastTilt_ = tilt;
        reset();
        return still && tilt > p_.posture_deg;
      }
      break;
    }
  }
  return false;
}
