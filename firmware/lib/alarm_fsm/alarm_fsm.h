// Máy trạng thái cảnh báo té — C++ thuần, test được trên máy tính (pio test -e native).
//
//   IDLE --start()--> SUSPECTED --(nhấn nút)--------------------> IDLE      phát CANCELLED
//                               --(lệnh hủy từ Pi, record.py)----> IDLE      phát AUTO_CANCELLED
//                               --(hết cancel_ms)----------------> CONFIRMED phát CONFIRMED
//                     CONFIRMED --(nhấn nút lần đầu)---------------> tắt còi (vẫn CONFIRMED) phát SILENCED
//                               --(lệnh hủy / hết confirmed_ms)---> IDLE
//
// Mọi mốc thời gian dùng cùng một `now` do người gọi đưa vào, và phép trừ tính có dấu: bản cũ đặt mốc bằng
// millis() mới hơn `now` của vòng lặp 1 ms, `now - since` (không dấu) tràn thành số rất lớn và xác nhận té
// ngay lập tức, không cho người đeo hủy (gặp ở phiên "ngã sau, lần 3" của S01 ngày 18/11/2026).
#pragma once
#include <stdint.h>

class AlarmFsm {
 public:
  enum State : uint8_t { IDLE = 0, SUSPECTED = 1, CONFIRMED = 2 };  // cùng thứ tự với AlarmState (app.h)
  // SILENCED: người đeo nhấn nút sau khi té đã xác nhận. Không hủy cảnh báo (đã gửi người thân), chỉ báo thêm
  // "người đeo còn phản hồi"; người thân vẫn phải kiểm tra rồi bấm Đã xử lý.
  enum Event : uint8_t { NONE, CANCELLED, AUTO_CANCELLED, CONFIRMED_EVT, SILENCED };

  AlarmFsm(uint32_t cancel_ms, uint32_t confirmed_ms) : cancel_(cancel_ms), confirmed_(confirmed_ms) {}

  // Bắt đầu nghi té. Đang cảnh báo thì bỏ qua (trả false).
  bool start(uint32_t now) {
    if (state_ != IDLE) return false;
    state_ = SUSPECTED;
    since_ = now;
    silenced_ = false;
    return true;
  }

  // pressed: nút vừa được nhấn; cancel: lệnh hủy từ Pi. Trả sự kiện cần gửi lên Pi.
  Event update(uint32_t now, bool pressed, bool cancel) {
    const int32_t el = (int32_t)(now - since_);
    switch (state_) {
      case SUSPECTED:
        if (pressed) {
          state_ = IDLE;
          return CANCELLED;
        }
        if (cancel) {
          state_ = IDLE;
          return AUTO_CANCELLED;
        }
        if (el >= (int32_t)cancel_) {
          state_ = CONFIRMED;
          since_ = now;
          return CONFIRMED_EVT;
        }
        break;
      case CONFIRMED:
        if (cancel || el >= (int32_t)confirmed_) {
          state_ = IDLE;
          break;
        }
        if (pressed && !silenced_) {  // tắt còi; cảnh báo đã gửi đi. Chỉ báo lần nhấn đầu
          silenced_ = true;
          return SILENCED;
        }
        break;
      default:
        break;
    }
    return NONE;
  }

  State state() const { return state_; }
  bool silenced() const { return silenced_; }
  uint32_t since() const { return since_; }

 private:
  uint32_t cancel_, confirmed_;
  State state_ = IDLE;
  uint32_t since_ = 0;
  bool silenced_ = false;
};
