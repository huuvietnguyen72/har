// Task giao diện (10 ms): nút, máy trạng thái cảnh báo té, LED, còi.
//
// Nút:   đang cảnh báo: nhấn 1 lần = hủy (hoặc tắt còi sau khi đã xác nhận)
//        bình thường  : nhấn 1 lần = bật màn hình, nhấn đúp = marker, giữ 3 s = SOS
// LED xanh: sáng = đã kết nối MQTT, nháy chậm = đang kết nối
// LED đỏ  : nháy nhanh = đang cảnh báo, sáng = lỗi cảm biến, nháy chậm = pin < 3,4 V
#include "app.h"
#include "button.h"
#include "pins.h"
#include "secrets.h"

namespace {

Button button(30, DOUBLE_PRESS_MS, LONG_PRESS_MS);
uint32_t buzzUntil = 0;  // còi kêu liên tục đến thời điểm này (buzzerPulse)

struct Alarm {
  AlarmState state = ALARM_IDLE;
  String id;  // id sự kiện suspected
  uint64_t impactT = 0;
  float peak = 0;
  uint32_t since = 0;
  bool silenced = false;
} al;

void buzzer(bool on) {
#if BUZZER_PASSIVE
  static bool cur = false;
  if (on != cur) {
    cur = on;
    if (on) ledcWriteTone(0, BUZZER_FREQ_HZ);
    else ledcWriteTone(0, 0);
  }
#else
  digitalWrite(PIN_BUZZER, on);
#endif
#if USE_VIBRATION
  digitalWrite(PIN_VIBRATION, on);
#endif
}

String eventJson(const String& id, const char* type, uint64_t t, const char* extra = "") {
  char b[256];
  snprintf(b, sizeof(b), "{\"v\":1,\"id\":\"%s\",\"type\":\"%s\",\"t\":%llu%s}", id.c_str(), type, (unsigned long long)t, extra);
  return String(b);
}

void emitSimple(const char* type) {
  String id = newEventId();
  eventSave(id, eventJson(id, type, epochMs()));
}

void startAlarm(const FallTrigger& ft) {
  if (al.state != ALARM_IDLE) return;  // đang cảnh báo: bỏ qua va chạm tiếp theo
  al.state = ALARM_SUSPECTED;
  al.impactT = ft.t;
  al.peak = ft.peak_g;
  al.since = millis();
  al.silenced = false;
  char id[40];
  snprintf(id, sizeof(id), "%s-%llu", DEVICE_ID, (unsigned long long)ft.t);
  al.id = id;
  char extra[48];
  snprintf(extra, sizeof(extra), ",\"peak_g\":%.2f", ft.peak_g);
  eventSave(al.id, eventJson(al.id, "suspected", ft.t, extra));
  displayWake();
}

void finishAlarm(const char* type) {
  String id = newEventId();
  char extra[96];
  snprintf(extra, sizeof(extra), ",\"ref\":\"%s\",\"peak_g\":%.2f", al.id.c_str(), al.peak);
  eventSave(id, eventJson(id, type, epochMs(), extra));
}

}  // namespace

void buzzerPulse(uint32_t ms) { buzzUntil = millis() + ms; }

void uiBegin() {
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
#if BUZZER_PASSIVE
  ledcSetup(0, BUZZER_FREQ_HZ, 8);
  ledcAttachPin(PIN_BUZZER, 0);
#else
  pinMode(PIN_BUZZER, OUTPUT);
#endif
#if USE_VIBRATION
  pinMode(PIN_VIBRATION, OUTPUT);
#endif
  buzzer(false);
}

void uiTask(void*) {
  TickType_t last = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&last, pdMS_TO_TICKS(10));
    const uint32_t now = millis();
    const uint8_t ev = button.update(digitalRead(PIN_BUTTON) == LOW, now);

    FallTrigger ft;
    if (xQueueReceive(fallQueue, &ft, 0) == pdTRUE) startAlarm(ft);

    // --- máy trạng thái cảnh báo ---
    switch (al.state) {
      case ALARM_SUSPECTED:
        if (ev & Button::PRESS) {  // người đeo vẫn ổn
          finishAlarm("cancelled");
          al.state = ALARM_IDLE;
          buzzerPulse(80);
        } else if (now - al.since >= CANCEL_WINDOW_MS) {
          finishAlarm("confirmed");
          al.state = ALARM_CONFIRMED;
          al.since = now;
        }
        break;
      case ALARM_CONFIRMED:
        if (ev & Button::PRESS) al.silenced = true;  // tắt còi; cảnh báo đã gửi đi
        if (now - al.since >= CONFIRMED_BUZZ_MS) al.state = ALARM_IDLE;
        break;
      case ALARM_IDLE:
        if (ev & Button::LONG) {
          emitSimple("sos");
          buzzerPulse(1000);
          displayWake();
        } else if (ev & Button::DOUBLE) {
          emitSimple("marker");
          buzzerPulse(60);
        } else if (ev & Button::SINGLE) {
          displayWake();
        }
        break;
    }
    g.alarm = al.state;
    g.alarmUntilMs = al.state == ALARM_SUSPECTED ? al.since + CANCEL_WINDOW_MS : 0;

    // --- còi ---
    bool buzz = now < buzzUntil;
    if (al.state == ALARM_SUSPECTED) buzz = buzz || (now % 500) < 200;  // ngắt quãng
    if (al.state == ALARM_CONFIRMED && !al.silenced) buzz = true;   // liên tục 30 s
    buzzer(buzz);

    // --- LED ---
    const bool slow = (now % 1000) < 500;
    const bool fast = (now % 200) < 100;
    digitalWrite(PIN_LED_GREEN, g.mqttUp ? HIGH : slow);
    bool red;
    if (al.state != ALARM_IDLE) red = fast;
    else if (!g.mpuOk) red = true;
    else if (!isnan(g.battery_v) && g.battery_v > 1.0f && g.battery_v < LOW_BATTERY_V) red = slow;
    else red = false;
    digitalWrite(PIN_LED_RED, red);
  }
}
