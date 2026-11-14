// OLED 0,96" SSD1315 (tương thích SSD1306) trên bus I2C thứ hai (GPIO18/19), task ưu tiên thấp,
// vẽ tối đa 2 lần/giây, tự tắt sau 15 s; bật lại khi nhấn nút, khi cảnh báo hoặc khi Pi gửi lệnh.
#include "app.h"
#include "pins.h"
#include "secrets.h"

#if USE_OLED
#include <U8g2lib.h>
#include <Wire.h>

namespace {
U8G2_SSD1306_128X64_NONAME_F_2ND_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
bool ready = false, on = true;

const char* labelVi(const char* l) {
  if (!strcmp(l, "stand")) return "Đứng";
  if (!strcmp(l, "sit")) return "Ngồi";
  if (!strcmp(l, "lie")) return "Nằm";
  if (!strcmp(l, "walk")) return "Đi";
  if (!strcmp(l, "run")) return "Chạy";
  if (!strcmp(l, "stairs_up")) return "Lên cầu thang";
  if (!strcmp(l, "stairs_down")) return "Xuống c.thang";
  if (!strcmp(l, "fall")) return "Té!";
  return l;
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

void draw() {
  char line[40];
  char label[16], mode[12], activity[16];
  float conf;
  xSemaphoreTake(stateMutex, portMAX_DELAY);
  strlcpy(label, g.label, sizeof(label));
  strlcpy(mode, g.mode, sizeof(mode));
  strlcpy(activity, g.activity, sizeof(activity));
  conf = g.conf;
  xSemaphoreGive(stateMutex);

  oled.clearBuffer();
  // dòng trạng thái (font nhỏ ASCII)
  oled.setFont(u8g2_font_6x10_tf);
  int pct = batteryPct(g.battery_v);
  snprintf(line, sizeof(line), "%s %s %s", DEVICE_ID, g.mqttUp ? "MQTT" : (g.wifiUp ? "WiFi.." : "noWiFi"),
           g.timeSynced ? "" : "noNTP");
  oled.drawStr(0, 9, line);
  if (pct >= 0) {
    snprintf(line, sizeof(line), "%d%%", pct);
    oled.drawStr(128 - oled.getStrWidth(line), 9, line);
  }
  oled.drawHLine(0, 12, 128);

  oled.setFont(u8g2_font_unifont_t_vietnamese2);
  if (g.alarm == ALARM_SUSPECTED) {
    oled.drawUTF8(0, 32, "NGHI TÉ NGÃ!");
    int left = (int)((int32_t)(g.alarmUntilMs - millis()) / 1000) + 1;
    snprintf(line, sizeof(line), "Nhấn nút để hủy %ds", left < 0 ? 0 : left);
    oled.drawUTF8(0, 54, line);
  } else if (g.alarm == ALARM_CONFIRMED) {
    oled.drawUTF8(0, 32, "ĐÃ GỬI CẢNH BÁO");
    oled.drawUTF8(0, 54, "Nhấn để tắt còi");
  } else if (!strcmp(mode, "record")) {
    oled.drawUTF8(0, 32, "● ĐANG THU");
    oled.drawUTF8(0, 54, activity[0] ? labelVi(activity) : "");
  } else {
    oled.drawUTF8(0, 34, label[0] ? labelVi(label) : "…");
    oled.setFont(u8g2_font_6x10_tf);
    if (!isnan(conf)) {
      snprintf(line, sizeof(line), "tin cay %d%%", (int)(conf * 100));
      oled.drawStr(0, 50, line);
    }
    if (!isnan(g.temp_c)) {
      snprintf(line, sizeof(line), "%.1fC %.0f%%RH  %ddBm", g.temp_c, g.rh, g.rssi);
      oled.drawStr(0, 63, line);
    }
  }
  oled.sendBuffer();
}
}  // namespace

void displayWake() { g.displayWakeMs = millis(); }

void displayBegin() {
  Wire1.begin(PIN_I2C2_SDA, PIN_I2C2_SCL, 400000);
  ready = oled.begin();
  if (ready) oled.enableUTF8Print();
  displayWake();
}

void displayTask(void*) {
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(DISPLAY_REFRESH_MS));
    if (!ready) continue;
    const bool want = g.alarm != ALARM_IDLE || millis() - g.displayWakeMs < DISPLAY_TIMEOUT_MS;
    if (want != on) {
      on = want;
      oled.setPowerSave(!on);
    }
    if (on) draw();
  }
}

#else
void displayWake() {}
void displayBegin() {}
void displayTask(void*) { vTaskDelete(nullptr); }
#endif
