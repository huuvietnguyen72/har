// Nhận dạng thao tác nút — C++ thuần, test được trên máy tính.
//   PRESS  : ngay khi nhấn (đã chống dội) — dùng để hủy cảnh báo tức thì
//   SINGLE : nhấn 1 lần (phát sau khi hết thời gian chờ nhấn đúp)
//   DOUBLE : nhấn đúp
//   LONG   : giữ ≥ long_ms (phát ngay khi đủ thời gian, không chờ nhả)
#pragma once
#include <stdint.h>

class Button {
 public:
  enum Event : uint8_t { NONE = 0, PRESS = 1, SINGLE = 2, DOUBLE = 4, LONG = 8 };

  explicit Button(uint32_t debounce_ms = 30, uint32_t double_ms = 400, uint32_t long_ms = 3000)
      : debounce_(debounce_ms), double_(double_ms), long_(long_ms) {}

  // pressed = true khi nút đang được nhấn. Trả về tổ hợp bit Event.
  uint8_t update(bool pressed, uint32_t now) {
    uint8_t ev = NONE;
    if (pressed != raw_) {
      raw_ = pressed;
      rawChanged_ = now;
    }
    if (raw_ != stable_ && now - rawChanged_ >= debounce_) {
      stable_ = raw_;
      if (stable_) {  // vừa nhấn
        ev |= PRESS;
        pressAt_ = now;
        longFired_ = false;
        clicks_++;
      } else {  // vừa nhả
        releaseAt_ = now;
        if (longFired_) clicks_ = 0;
      }
    }
    if (stable_ && !longFired_ && now - pressAt_ >= long_) {
      longFired_ = true;
      clicks_ = 0;
      ev |= LONG;
    }
    if (!stable_ && clicks_ > 0) {
      if (clicks_ >= 2) {
        ev |= DOUBLE;
        clicks_ = 0;
      } else if (now - releaseAt_ >= double_) {
        ev |= SINGLE;
        clicks_ = 0;
      }
    }
    return ev;
  }

  bool isDown() const { return stable_; }

 private:
  uint32_t debounce_, double_, long_;
  bool raw_ = false, stable_ = false, longFired_ = false;
  uint32_t rawChanged_ = 0, pressAt_ = 0, releaseAt_ = 0;
  uint8_t clicks_ = 0;
};
