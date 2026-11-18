// Luồng hiệu chỉnh hướng đứng thẳng bằng nút (nhấn 3 lần) — C++ thuần, test được trên máy tính.
//
//   start()  -> COUNTDOWN (người đeo buông tay, đứng thẳng; mặc định 2 s)
//            -> MEASURING (uiTask gửi requestUprightCal; chờ kết quả, tối đa timeout)
//            -> OK / FAIL (hiện kết quả show_ms rồi về IDLE)
// update() nhận kết quả hiện tại của lần đo: 0 = chưa có (pending), 1 = ok, 2 = không đạt.
// Mọi phép trừ thời gian tính có dấu (như alarm_fsm) để mốc mới hơn `now` không làm tràn số.
#pragma once
#include <stdint.h>

class CalFlow {
 public:
  enum Phase : uint8_t { IDLE = 0, COUNTDOWN = 1, MEASURING = 2, OK = 3, FAIL = 4 };
  enum Action : uint8_t { NONE = 0, BEGIN_MEASURE, DONE_OK, DONE_FAIL };

  explicit CalFlow(uint32_t countdown_ms = 2000, uint32_t timeout_ms = 15000, uint32_t show_ms = 5000)
      : countdown_(countdown_ms), timeout_(timeout_ms), show_(show_ms) {}

  // Bắt đầu; bỏ qua nếu đang đếm ngược hoặc đang đo.
  bool start(uint32_t now) {
    if (busy()) return false;
    phase_ = COUNTDOWN;
    since_ = now;
    return true;
  }

  void abort() { phase_ = IDLE; }

  Action update(uint32_t now, int result) {
    const int32_t el = (int32_t)(now - since_);
    switch (phase_) {
      case COUNTDOWN:
        if (el >= (int32_t)countdown_) {
          phase_ = MEASURING;
          since_ = now;
          return BEGIN_MEASURE;
        }
        break;
      case MEASURING:
        if (result == 1 || result == 2 || el >= (int32_t)timeout_) {
          phase_ = result == 1 ? OK : FAIL;
          since_ = now;
          return result == 1 ? DONE_OK : DONE_FAIL;
        }
        break;
      case OK:
      case FAIL:
        if (el >= (int32_t)show_) phase_ = IDLE;
        break;
      default:
        break;
    }
    return NONE;
  }

  Phase phase() const { return phase_; }
  bool busy() const { return phase_ == COUNTDOWN || phase_ == MEASURING; }

  // Số giây còn lại của bước đếm ngược (làm tròn lên), 0 ở các bước khác.
  int leftS(uint32_t now) const {
    if (phase_ != COUNTDOWN) return 0;
    const int32_t left = (int32_t)countdown_ - (int32_t)(now - since_);
    return left <= 0 ? 0 : (left + 999) / 1000;
  }

 private:
  uint32_t countdown_, timeout_, show_;
  Phase phase_ = IDLE;
  uint32_t since_ = 0;
};
