// Firmware bộ đeo HAR (ESP32 DevKit, Arduino framework).
// Thiết kế: kế hoạch giai đoạn 2; chân: include/pins.h; payload MQTT: docs/mqtt.md.
#include "app.h"
#include "pins.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Thiếu include/secrets.h — copy include/secrets.example.h thành secrets.h rồi điền"
#endif

SharedState g;
SemaphoreHandle_t i2cMutex, stateMutex, eventMutex;
QueueHandle_t imuQueue, envQueue, fallQueue;
TaskHandle_t netTaskHandle = nullptr;
FallDetector fallDetector;

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n=== HAR firmware %s (%s) ===\n", FW_VERSION, DEVICE_ID);

  i2cMutex = xSemaphoreCreateMutex();
  stateMutex = xSemaphoreCreateMutex();
  eventMutex = xSemaphoreCreateMutex();
  imuQueue = xQueueCreate(RING_PACKETS, sizeof(ImuPacket));  // ~37 KB = 60 s dữ liệu
  envQueue = xQueueCreate(RING_PACKETS, sizeof(EnvPacket));
  fallQueue = xQueueCreate(4, sizeof(FallTrigger));
  if (!imuQueue || !envQueue) Serial.println("[main] KHÔNG đủ RAM cho vòng đệm!");

  uiBegin();
  eventsBegin();
  loadThresholds();
  sensorsBegin();
  displayBegin();

  // core 1: lấy mẫu (ưu tiên cao nhất) ; core 0: mạng, giao diện, màn hình (cùng core với Wi-Fi)
  xTaskCreatePinnedToCore(samplerTask, "sampler", 4096, nullptr, 5, nullptr, 1);
  xTaskCreatePinnedToCore(slowTask, "slow", 3072, nullptr, 2, nullptr, 1);
  xTaskCreatePinnedToCore(uiTask, "ui", 4096, nullptr, 4, nullptr, 0);
  xTaskCreatePinnedToCore(netTask, "net", 12288, nullptr, 3, &netTaskHandle, 0);
  xTaskCreatePinnedToCore(displayTask, "display", 4096, nullptr, 1, nullptr, 0);
}

void loop() {
  // Mọi việc chạy trong task FreeRTOS. Ở đây chỉ in thống kê mỗi 10 s để debug qua Serial.
  static uint32_t lastSamples = 0;
  vTaskDelay(pdMS_TO_TICKS(10000));
  const uint32_t s = g.samples;
  Serial.printf("[stat] %.1f Hz, imuQ=%u envQ=%u bỏ=%lu wifi=%d mqtt=%d ntp=%d pin=%.2fV heap=%u\n",
                (s - lastSamples) / 10.0f, (unsigned)uxQueueMessagesWaiting(imuQueue),
                (unsigned)uxQueueMessagesWaiting(envQueue), (unsigned long)g.dropped, g.wifiUp, g.mqttUp,
                g.timeSynced, g.battery_v, (unsigned)ESP.getFreeHeap());
  lastSamples = s;
}
