// Khai báo dùng chung giữa các task.
//
//   samplerTask (core 1, ưu tiên 5): MPU6050 50 Hz, BMP280 10 Hz, bộ phát hiện té → imuQueue/envQueue
//   slowTask    (core 1, ưu tiên 2): AHT20 + áp pin mỗi 10 s
//   netTask     (core 0, ưu tiên 3): Wi-Fi, MQTT, NTP, xả hàng đợi, gửi lại sự kiện đến khi có ack
//   uiTask      (core 0, ưu tiên 4): nút, máy trạng thái cảnh báo, LED, còi
//   displayTask (core 0, ưu tiên 1): OLED trên bus I2C thứ hai
#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

#include "config.h"
#include "fall_detector.h"

struct ImuPacket {
  uint32_t seq;
  uint64_t t0;  // epoch ms của mẫu đầu
  uint32_t createdMs;  // millis() lúc đóng gói, để biết gói có phải gửi bù không
  int16_t v[6][PACKET_SAMPLES];  // ax, ay, az, gx, gy, gz (thô)
};

struct EnvPacket {
  uint32_t seq;
  uint64_t t0;
  uint32_t createdMs;
  uint8_t n;
  float p[ENV_PACKET_SAMPLES];
  float temp_c, rh;  // NAN nếu không có số mới
};

struct FallTrigger {
  uint64_t t;  // thời điểm va chạm
  float peak_g;
};

enum AlarmState : uint8_t { ALARM_IDLE, ALARM_SUSPECTED, ALARM_CONFIRMED };

struct SharedState {
  // cập nhật bởi slowTask / samplerTask
  float battery_v = NAN;
  float temp_c = NAN, rh = NAN;
  bool thFresh = false;
  bool mpuOk = false, bmpOk = false, ahtOk = false;
  uint32_t samples = 0;
  // cập nhật bởi netTask
  bool wifiUp = false, mqttUp = false, timeSynced = false;
  int rssi = 0;
  uint32_t dropped = 0;  // gói bị bỏ do vòng đệm đầy
  // từ Pi (har/{dev}/display và cmd)
  char label[16] = "";
  float conf = NAN;
  char mode[12] = "monitor";
  char activity[16] = "";
  // uiTask
  AlarmState alarm = ALARM_IDLE;
  uint32_t alarmUntilMs = 0;
  uint32_t displayWakeMs = 0;
};

extern SharedState g;
extern SemaphoreHandle_t i2cMutex;    // bus 1: MPU6050 + BMP280 + AHT20
extern SemaphoreHandle_t stateMutex;  // bảo vệ chuỗi trong SharedState
extern SemaphoreHandle_t eventMutex;  // LittleFS sự kiện
extern QueueHandle_t imuQueue, envQueue, fallQueue;
extern TaskHandle_t netTaskHandle;
extern FallDetector fallDetector;

// time.cpp
uint64_t epochMs();
bool timeValid();

// sensors.cpp
bool sensorsBegin();
void samplerTask(void*);
void slowTask(void*);

// events.cpp — sự kiện lưu LittleFS đến khi Pi xác nhận
bool eventsBegin();
String newEventId();
bool eventSave(const String& id, const String& json);
void eventAck(const String& id);
int eventCount();
// Gọi fn(id, json) cho từng sự kiện đang chờ; dừng nếu fn trả false
void eventForEach(bool (*fn)(const String& id, const String& json));
void loadThresholds();
void saveThresholds();

// net.cpp
void netTask(void*);
void requestStatusNow();

// ui.cpp
void uiBegin();
void uiTask(void*);
void buzzerPulse(uint32_t ms);

// display.cpp
void displayBegin();
void displayTask(void*);
void displayWake();
