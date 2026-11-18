// Task giao diện (10 ms): nút, máy trạng thái cảnh báo té, LED, còi.
//
// Nút:   đang cảnh báo: nhấn 1 lần = hủy (hoặc tắt còi sau khi đã xác nhận)
//        bình thường  : nhấn 1 lần = bật màn hình, nhấn đúp = marker, nhấn 3 lần = hiệu chỉnh hướng đứng
//                       thẳng (đứng thẳng yên ~4 s), giữ 3 s = SOS
// LED xanh: sáng = đã kết nối MQTT, nháy chậm = đang kết nối
// LED đỏ  : nháy nhanh = đang cảnh báo, sáng = lỗi cảm biến, nháy chậm = pin < 3,4 V
#include "alarm_fsm.h"
#include "app.h"
#include "button.h"
#include "cal_flow.h"
#include "pins.h"
#include "secrets.h"

namespace {

Button button(30, DOUBLE_PRESS_MS, LONG_PRESS_MS);
uint32_t buzzUntil = 0;  // còi kêu liên tục đến thời điểm này (buzzerPulse)

AlarmFsm fsm(CANCEL_WINDOW_MS, CONFIRMED_BUZZ_MS);  // lib/alarm_fsm: trạng thái + thời gian
volatile bool alarmCancelRequest = false;          // netTask (lệnh cancel_alarm) -> uiTask

// Hiệu chỉnh hướng đứng thẳng bằng nút (lib/cal_flow)
CalFlow cal(CAL_COUNTDOWN_MS, CAL_TIMEOUT_MS, CAL_SHOW_MS);
char calId[24] = "";
// Chuỗi tiếng bíp: n lần, mỗi lần on ms, nghỉ off ms
uint8_t beepsLeft = 0;
uint16_t beepOn = 0, beepOff = 0;
uint32_t beepNextAt = 0;

void buzzerBeeps(uint8_t n, uint16_t on, uint16_t off) {
  beepsLeft = n;
  beepOn = on;
  beepOff = off;
  beepNextAt = millis();
}

// Kết quả lần đo của chính luồng nút: 0 = chưa có, 1 = ok, 2 = không đạt (lệnh khác chen vào cũng tính là không đạt)
int calResult() {
  if (strcmp(g.uprightReq, calId) != 0) return 2;
  if (!strcmp(g.uprightResult, "ok")) return 1;
  if (!strcmp(g.uprightResult, "pending")) return 0;
  return 2;
}

struct Alarm {
  String id;  // id sự kiện suspected
  uint64_t impactT = 0;
  float peak = 0;
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

void startAlarm(const FallTrigger& ft, uint32_t now) {
  if (!fsm.start(now)) return;  // đang cảnh báo: bỏ qua va chạm tiếp theo
  al.impactT = ft.t;
  al.peak = ft.peak_g;
  char id[40];
  snprintf(id, sizeof(id), "%s-%llu", DEVICE_ID, (unsigned long long)ft.t);
  al.id = id;
  char extra[48];
  snprintf(extra, sizeof(extra), ",\"peak_g\":%.2f", ft.peak_g);
  eventSave(al.id, eventJson(al.id, "suspected", ft.t, extra));
  displayWake();
}

// by: nguồn kết thúc cảnh báo ("record" = record.py hủy khi hết phiên thu), nullptr = người đeo / hết giờ
void finishAlarm(const char* type, const char* by = nullptr) {
  String id = newEventId();
  char extra[112];
  snprintf(extra, sizeof(extra), ",\"ref\":\"%s\",\"peak_g\":%.2f%s%s%s", al.id.c_str(), al.peak,
           by ? ",\"by\":\"" : "", by ? by : "", by ? "\"" : "");
  eventSave(id, eventJson(id, type, epochMs(), extra));
}

}  // namespace

void buzzerPulse(uint32_t ms) { buzzUntil = millis() + ms; }

void requestAlarmCancel() { alarmCancelRequest = true; }

void uiBegin() {
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  delay(5);
  g.btnLevel = digitalRead(PIN_BUTTON);
  Serial.printf("[btn] GPIO%d lúc khởi động: %s\n", PIN_BUTTON,
                g.btnLevel ? "HIGH (nhả, đúng)" : "LOW (đang nối GND: nút kẹt hoặc đấu sai chân)");
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
    g.btnLevel = digitalRead(PIN_BUTTON);
    const uint8_t ev = button.update(!g.btnLevel, now);
    if (ev) {
      if (ev & Button::PRESS) g.btnPresses++;
      Serial.printf("[btn]%s%s%s%s (tổng %lu lần nhấn)\n", (ev & Button::PRESS) ? " nhấn" : "",
                    (ev & Button::SINGLE) ? " 1-lần" : "", (ev & Button::DOUBLE) ? " nhấn-đúp" : "",
                    (ev & Button::LONG) ? " giữ-3s" : "", (unsigned long)g.btnPresses);
    }

    FallTrigger ft;
    if (xQueueReceive(fallQueue, &ft, 0) == pdTRUE) startAlarm(ft, now);

    // --- máy trạng thái cảnh báo (lib/alarm_fsm) ---
    const bool wasIdle = fsm.state() == AlarmFsm::IDLE;
    const bool cancelReq = alarmCancelRequest;
    if (cancelReq) alarmCancelRequest = false;
    switch (fsm.update(now, ev & Button::PRESS, cancelReq)) {
      case AlarmFsm::CANCELLED:  // người đeo nhấn nút: vẫn ổn
        finishAlarm("cancelled");
        buzzerPulse(80);
        break;
      case AlarmFsm::AUTO_CANCELLED:  // record.py hủy khi hết phiên thu té
        finishAlarm("cancelled", "record");
        break;
      case AlarmFsm::CONFIRMED_EVT:
        finishAlarm("confirmed");
        break;
      default:
        break;
    }
    if (wasIdle) {
      if (ev & Button::LONG) {
        emitSimple("sos");
        buzzerPulse(1000);
        displayWake();
      } else if (ev & Button::DOUBLE) {
        emitSimple("marker");
        buzzerPulse(60);
      } else if (ev & Button::TRIPLE) {
        if (cal.start(now)) {
          buzzerBeeps(2, 80, 80);
          displayWake();
          Serial.println("[upright] nút: đứng thẳng, giữ yên — bắt đầu đo sau 2 s");
        }
      } else if (ev & Button::SINGLE) {
        displayWake();
      }
    }

    // --- hiệu chỉnh hướng đứng thẳng bằng nút ---
    if (fsm.state() != AlarmFsm::IDLE && cal.busy()) cal.abort();  // cảnh báo té được ưu tiên
    switch (cal.update(now, cal.phase() == CalFlow::MEASURING ? calResult() : 0)) {
      case CalFlow::BEGIN_MEASURE:
        snprintf(calId, sizeof(calId), "btn-%llu", (unsigned long long)(timeValid() ? epochMs() / 1000 : now / 1000));
        requestUprightCal(calId);
        buzzerBeeps(1, 80, 0);
        break;
      case CalFlow::DONE_OK:
        buzzerBeeps(1, 600, 0);
        displayWake();
        break;
      case CalFlow::DONE_FAIL:
        buzzerBeeps(3, 120, 120);
        displayWake();
        Serial.printf("[upright] nút: không đạt (%s)\n", g.uprightResult);
        break;
      default:
        break;
    }
    g.calPhase = cal.phase();
    g.calLeftS = cal.leftS(now);
    if (beepsLeft && (int32_t)(now - beepNextAt) >= 0) {
      buzzerPulse(beepOn);
      beepNextAt = now + beepOn + beepOff;
      beepsLeft--;
    }
    const AlarmState st = (AlarmState)fsm.state();
    g.alarm = st;
    g.alarmUntilMs = st == ALARM_SUSPECTED ? fsm.since() + CANCEL_WINDOW_MS : 0;

    // --- còi ---
    bool buzz = now < buzzUntil;
    // Đang thu dataset: cảnh báo không dùng loa (loa rung làm nhiễu gia tốc kế), LED đỏ + OLED vẫn báo
    const uint32_t rec = g.recordSinceMs;
    const bool quiet = rec != 0 && now - rec < RECORD_QUIET_MAX_MS;
    if (!quiet && st == ALARM_SUSPECTED) buzz = buzz || (now % 500) < 200;  // ngắt quãng
    if (!quiet && st == ALARM_CONFIRMED && !fsm.silenced()) buzz = true;  // liên tục 30 s
    buzzer(buzz);

    // --- LED ---
    const bool slow = (now % 1000) < 500;
    const bool fast = (now % 200) < 100;
    digitalWrite(PIN_LED_GREEN, g.mqttUp ? HIGH : slow);
    bool red;
    if (st != ALARM_IDLE) red = fast;
    else if (!g.mpuOk) red = true;
    else if (!isnan(g.battery_v) && g.battery_v > 1.0f && g.battery_v < LOW_BATTERY_V) red = slow;
    else red = false;
    digitalWrite(PIN_LED_RED, red);
  }
}
