// OLED 0,96" SSD1315 (tương thích SSD1306) trên bus I2C chọn bằng OLED_I2C_BUS (pins.h), task ưu tiên thấp,
// vẽ tối đa 2 lần/giây, luôn sáng (DISPLAY_TIMEOUT_MS = 0), giảm sáng sau DISPLAY_DIM_MS không nhấn nút.
#include "app.h"
#include "pins.h"

#if USE_OLED
#include <U8g2lib.h>
#include <Wire.h>

#include "oled_layout.h"

namespace {
#if OLED_I2C_BUS == 1
// Chung bus với cảm biến: mọi giao dịch I2C của màn phải giữ i2cMutex
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
#define OLED_LOCK() xSemaphoreTake(i2cMutex, portMAX_DELAY)
#define OLED_UNLOCK() xSemaphoreGive(i2cMutex)
#else
U8G2_SSD1306_128X64_NONAME_F_2ND_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
#define OLED_LOCK() ((void)0)
#define OLED_UNLOCK() ((void)0)
#endif
bool ready = false, on = true, dimmed = false;

// Gửi khung hình. Bus riêng: một lần. Chung bus: từng dải 8 dòng (128 B ≈ 3 ms ở 400 kHz),
// nhả bus giữa các dải — samplerTask chỉ chờ i2cMutex tối đa 8 ms nên không mất mẫu.
void sendFrame() {
#if OLED_I2C_BUS == 1
  for (uint8_t ty = 0; ty < 8; ty++) {
    OLED_LOCK();
    oled.updateDisplayArea(0, ty, 16, 1);
    OLED_UNLOCK();
    vTaskDelay(1);
  }
#else
  oled.sendBuffer();
#endif
}

int batteryPct(float v) {
  if (isnan(v)) return -1;
  const float pts[][2] = {{3.3f, 0}, {3.5f, 5}, {3.6f, 10}, {3.7f, 25}, {3.75f, 40}, {3.8f, 50},
                          {3.85f, 60}, {3.9f, 70}, {4.0f, 82}, {4.1f, 93}, {4.2f, 100}};
  if (v <= pts[0][0]) return 0;
  for (int i = 1; i < 11; i++)
    if (v <= pts[i][0])
      return (int)(pts[i - 1][1] + (v - pts[i - 1][0]) / (pts[i][0] - pts[i - 1][0]) * (pts[i][1] - pts[i - 1][1]));
  return 100;
}

// Gom trạng thái rồi vẽ bằng oledDraw() trong oled_layout.h (dùng chung với bản xem trước trên PC)
void draw() {
  char label[16], mode[12], activity[16], right[8] = "";
  float conf;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  strlcpy(label, g.label, sizeof(label));
  strlcpy(mode, g.mode, sizeof(mode));
  strlcpy(activity, g.activity, sizeof(activity));
  conf = g.conf;
  xSemaphoreGive(stateMutex);

  // Góc phải: % pin nếu đo được, không thì giờ Việt Nam HH:MM từ Pi (mạch hiện tại không đo áp pin)
  if (!isnan(g.battery_v)) {
    snprintf(right, sizeof(right), "%d%%", batteryPct(g.battery_v));
  } else if (g.timeSynced) {
    const time_t now = time(nullptr) + 7 * 3600;  // configTime(0, 0): đồng hồ hệ thống là UTC
    struct tm tmv;
    gmtime_r(&now, &tmv);
    snprintf(right, sizeof(right), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
  }
  const bool recording = !strcmp(mode, "record");
  OledView v;
  v.conn = g.mqttUp ? "MQTT" : (g.wifiUp ? "WiFi.." : "noWiFi");
  v.ntpOk = g.timeSynced;
  v.right = right;
  v.ssid = wifiSsid();
  v.alarm = g.alarm == ALARM_SUSPECTED ? OLED_SUSPECTED : g.alarm == ALARM_CONFIRMED ? OLED_CONFIRMED : OLED_IDLE;
  v.alarmLeftS = (int)((int32_t)(g.alarmUntilMs - millis()) / 1000) + 1;
  v.recording = recording;
  v.cal = g.calPhase;
  v.calLeftS = g.calLeftS;
  char calResult[12];
  strlcpy(calResult, g.uprightResult, sizeof(calResult));
  v.calResult = calResult;
  v.label = recording ? activity : label;
  v.conf = recording ? NAN : conf;
  oledDraw(oled.getU8g2(), &v);
  sendFrame();
}
}  // namespace

// Dò I2C lúc khởi động (chưa có task nào chạy nên không cần i2cMutex). Trả về true nếu thấy addr.
bool scanBus(TwoWire& bus, const char* name, uint8_t want) {
  char found[128] = "";
  bool hit = false;
  for (uint8_t a = 1; a < 127; a++) {
    bus.beginTransmission(a);
    if (bus.endTransmission() == 0) {
      snprintf(found + strlen(found), sizeof(found) - strlen(found), " 0x%02X", a);
      hit |= (a == want);
    }
  }
  Serial.printf("[i2c] %s:%s\n", name, found[0] ? found : " (không có thiết bị)");
  return hit;
}

void displayWake() { g.displayWakeMs = millis(); }

void displayBegin() {
  char name[32];
  snprintf(name, sizeof(name), "bus1 SDA%d/SCL%d", PIN_I2C1_SDA, PIN_I2C1_SCL);
  const bool onBus1 = scanBus(Wire, name, 0x3C);
  bool onBus2 = false;
#if BUS2_PINS_FREE
  Wire1.begin(PIN_I2C2_SDA, PIN_I2C2_SCL, 400000);
  snprintf(name, sizeof(name), "bus2 SDA%d/SCL%d", PIN_I2C2_SDA, PIN_I2C2_SCL);
  onBus2 = scanBus(Wire1, name, 0x3C);
#else
  Serial.printf("[i2c] bus2 không bật: GPIO%d đang dùng cho nút\n", PIN_BUTTON);
#endif
  const bool onConfigured = OLED_I2C_BUS == 1 ? onBus1 : onBus2;
  if (onConfigured) Serial.printf("[oled] thấy OLED 0x3C trên bus%d — OK\n", OLED_I2C_BUS);
  else if (onBus1 || onBus2)
    Serial.printf("[oled] OLED 0x3C nằm trên bus%d nhưng firmware đặt OLED_I2C_BUS=%d (include/pins.h)\n",
                  onBus1 ? 1 : 2, OLED_I2C_BUS);
  else Serial.println("[oled] KHÔNG thấy OLED 0x3C — kiểm tra dây SDA/SCL/VCC/GND");
  OLED_LOCK();
  oled.setBusClock(400000);  // giữ đúng xung nhịp bus cảm biến (U8g2 đặt lại clock mỗi lần gửi)
  ready = oled.begin();
  if (ready) oled.setContrast(255);
  OLED_UNLOCK();
  if (ready) oled.enableUTF8Print();
  displayWake();
}

void displayTask(void*) {
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(DISPLAY_REFRESH_MS));
    if (!ready) continue;
    const uint32_t idle = millis() - g.displayWakeMs;
    const bool alarm = g.alarm != ALARM_IDLE || g.calPhase != 0;  // cảnh báo hoặc đang hiệu chỉnh: luôn sáng
    const bool want = alarm || DISPLAY_TIMEOUT_MS == 0 || idle < (uint32_t)DISPLAY_TIMEOUT_MS;
    const bool dim = !alarm && DISPLAY_DIM_MS > 0 && idle >= (uint32_t)DISPLAY_DIM_MS;
    if (want != on) {
      on = want;
      OLED_LOCK();
      oled.setPowerSave(!on);
      OLED_UNLOCK();
    }
    if (dim != dimmed) {  // giảm sáng khi lâu không ai nhấn nút để đỡ lưu ảnh trên OLED
      dimmed = dim;
      OLED_LOCK();
      oled.setContrast(dim ? 16 : 255);
      OLED_UNLOCK();
    }
    if (on) draw();
  }
}

#else
void displayWake() {}
void displayBegin() {}
void displayTask(void*) { vTaskDelete(nullptr); }
#endif
