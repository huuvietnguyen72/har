// Sự kiện (suspected/cancelled/confirmed/sos/marker) lưu mỗi sự kiện một file /ev/<id>.json
// trên LittleFS: không mất khi tắt nguồn; netTask gửi lại mỗi 5 s đến khi Pi trả har/{dev}/ack.
// Ngưỡng té lưu trong NVS (Preferences).
#include <LittleFS.h>
#include <Preferences.h>
#include <sys/time.h>

#include "app.h"
#include "secrets.h"

uint64_t epochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000;
}

bool timeValid() { return time(nullptr) > 1700000000; }  // sau 11/2023 = đã đồng bộ NTP

bool eventsBegin() {
  if (!LittleFS.begin(true)) {  // true: tự format lần đầu
    Serial.println("[events] LittleFS lỗi");
    return false;
  }
  if (!LittleFS.exists("/ev")) LittleFS.mkdir("/ev");
  Serial.printf("[events] %d sự kiện chờ gửi\n", eventCount());
  return true;
}

String newEventId() {
  static uint32_t counter = 0;
  if (timeValid()) {
    uint64_t t = epochMs();
    char buf[40];
    snprintf(buf, sizeof(buf), "%s-%llu", DEVICE_ID, (unsigned long long)t);
    return String(buf);
  }
  // chưa có giờ: id vẫn phải duy nhất
  char buf[40];
  snprintf(buf, sizeof(buf), "%s-u%08lx%04lx", DEVICE_ID, (unsigned long)esp_random(), (unsigned long)(counter++ & 0xFFFF));
  return String(buf);
}

static String pathFor(const String& id) { return "/ev/" + id + ".json"; }

int eventCount() {
  int n = 0;
  xSemaphoreTake(eventMutex, portMAX_DELAY);
  File dir = LittleFS.open("/ev");
  if (dir) {
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) n++;
  }
  xSemaphoreGive(eventMutex);
  return n;
}

bool eventSave(const String& id, const String& json) {
  if (eventCount() >= MAX_STORED_EVENTS) {  // tránh đầy flash: bỏ file cũ nhất (marker trước)
    xSemaphoreTake(eventMutex, portMAX_DELAY);
    File dir = LittleFS.open("/ev");
    String oldest;
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      String name = String("/ev/") + f.name();
      if (oldest.isEmpty() || name < oldest) oldest = name;
    }
    if (!oldest.isEmpty()) LittleFS.remove(oldest);
    xSemaphoreGive(eventMutex);
  }
  xSemaphoreTake(eventMutex, portMAX_DELAY);
  File f = LittleFS.open(pathFor(id), "w");
  bool ok = f && f.print(json) == json.length();
  if (f) f.close();
  xSemaphoreGive(eventMutex);
  if (netTaskHandle) xTaskNotifyGive(netTaskHandle);  // gửi ngay
  Serial.printf("[event] %s\n", json.c_str());
  return ok;
}

void eventAck(const String& id) {
  xSemaphoreTake(eventMutex, portMAX_DELAY);
  LittleFS.remove(pathFor(id));
  xSemaphoreGive(eventMutex);
}

void eventForEach(bool (*fn)(const String& id, const String& json)) {
  // Đọc danh sách trước rồi mới gọi fn để không giữ mutex lâu
  String ids[MAX_STORED_EVENTS + 2];
  String bodies[MAX_STORED_EVENTS + 2];
  int n = 0;
  xSemaphoreTake(eventMutex, portMAX_DELAY);
  File dir = LittleFS.open("/ev");
  for (File f = dir.openNextFile(); f && n < MAX_STORED_EVENTS + 2; f = dir.openNextFile()) {
    String name = f.name();
    if (!name.endsWith(".json")) continue;
    ids[n] = name.substring(0, name.length() - 5);
    bodies[n] = f.readString();
    n++;
  }
  xSemaphoreGive(eventMutex);
  for (int i = 0; i < n; i++)
    if (!fn(ids[i], bodies[i])) break;
}

void loadThresholds() {
  Preferences p;
  p.begin("fall", true);
  FallParams& fp = fallDetector.params();
  fp.freefall_g = p.getFloat("ff_g", fp.freefall_g);
  fp.freefall_ms = p.getUInt("ff_ms", fp.freefall_ms);
  fp.impact_g = p.getFloat("imp_g", fp.impact_g);
  fp.impact_window_ms = p.getUInt("imp_win", fp.impact_window_ms);
  fp.still_gyro_dps = p.getFloat("still_gyro", fp.still_gyro_dps);
  fp.posture_deg = p.getFloat("posture", fp.posture_deg);
  p.end();
  Serial.printf("[fall] rơi<%.2fg %ums, va chạm>%.2fg, tư thế>%.0f°\n", fp.freefall_g, (unsigned)fp.freefall_ms,
                fp.impact_g, fp.posture_deg);
}

void saveThresholds() {
  Preferences p;
  p.begin("fall", false);
  const FallParams& fp = fallDetector.params();
  p.putFloat("ff_g", fp.freefall_g);
  p.putUInt("ff_ms", fp.freefall_ms);
  p.putFloat("imp_g", fp.impact_g);
  p.putUInt("imp_win", fp.impact_window_ms);
  p.putFloat("still_gyro", fp.still_gyro_dps);
  p.putFloat("posture", fp.posture_deg);
  p.end();
}
