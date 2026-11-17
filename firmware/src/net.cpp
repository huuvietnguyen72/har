// Task mạng (core 0): Wi-Fi, NTP từ Pi, MQTT (PubSubClient), xả hàng đợi, gửi lại sự kiện.
// Topic và payload: docs/mqtt.md
#include <ArduinoJson.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <esp_sntp.h>

#include "app.h"
#include "secrets.h"

namespace {

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
char buf[MQTT_BUFFER_SIZE];
String tImu, tEnv, tEvent, tStatus, tCmd, tDisplay, tAck;
IPAddress brokerIp;
bool brokerKnown = false, ntpStarted = false, mdnsStarted = false;
uint32_t lastStatus = 0, lastResend = 0, lastAttempt = 0;
volatile bool statusRequested = false;
const char* LWT = "{\"v\":1,\"online\":false}";

// --- giải tên Pi: "" -> gateway; *.local -> mDNS; còn lại -> DNS ---
bool resolveBroker() {
  String host = MQTT_HOST;
  IPAddress ip;
  if (host.length() == 0) {
    ip = WiFi.gatewayIP();
  } else if (ip.fromString(host)) {
    // đã là IP
  } else if (host.endsWith(".local")) {
    if (!mdnsStarted) mdnsStarted = MDNS.begin(DEVICE_ID);
    ip = MDNS.queryHost(host.substring(0, host.length() - 6), 2000);
    if (ip == IPAddress()) {
      ip = WiFi.gatewayIP();  // Pi phát hotspot thì gateway chính là Pi
      Serial.printf("[net] không tìm thấy %s qua mDNS, dùng gateway %s\n", host.c_str(), ip.toString().c_str());
    }
  } else if (!WiFi.hostByName(host.c_str(), ip)) {
    return false;
  }
  if (ip == IPAddress()) return false;
  brokerIp = ip;
  brokerKnown = true;
  Serial.printf("[net] broker %s -> %s\n", host.c_str(), ip.toString().c_str());
  return true;
}

IPAddress ntpIp;  // địa chỉ broker lúc khởi động NTP (khi NTP_HOST = "")

// NTP_HOST = "" thì máy chủ giờ đi theo broker. Lần đầu mDNS có thể lỡ -> tạm dùng gateway
// (router), MQTT lỗi -> giải tên lại ra Pi; khi đó phải khởi động lại NTP, nếu không sẽ kẹt
// hỏi giờ router mãi (ntp=0, không bao giờ gửi dữ liệu).
bool ntpNeedsStart() { return !ntpStarted || (!strlen(NTP_HOST) && ntpIp != brokerIp); }

void startNtp() {
  static String ntpHost;  // configTime giữ con trỏ, phải sống suốt chương trình
  ntpHost = strlen(NTP_HOST) ? String(NTP_HOST) : brokerIp.toString();
  // Mặc định ESP-IDF 1 giờ mới hỏi giờ lại. Pi không có RTC: vừa khởi động thì giờ Pi có thể sai
  // (đo được 12,3 s) cho tới khi chrony đồng bộ Internet. Hỏi lại mỗi NTP_SYNC_MS để sai lệch tự hết.
  sntp_set_sync_interval(NTP_SYNC_MS);
  configTime(0, 0, ntpHost.c_str());
  ntpIp = brokerIp;
  ntpStarted = true;
  Serial.printf("[ntp] máy chủ giờ %s\n", ntpHost.c_str());
}

void publishStatus() {
  // battery_v = null khi không đo được pin (Pi bỏ qua, không báo pin yếu sai)
  char bat[12] = "null";
  if (!isnan(g.battery_v)) snprintf(bat, sizeof(bat), "%.3f", g.battery_v);
  int n = snprintf(buf, sizeof(buf),
                   "{\"v\":1,\"t\":%llu,\"online\":true,\"battery_v\":%s,\"rssi\":%d,\"uptime_s\":%lu,\"fw\":\"%s\","
                   "\"heap\":%u,\"mpu_ok\":%s,\"bmp_ok\":%s,\"aht_ok\":%s,\"pending_events\":%d,\"dropped\":%lu,"
                   "\"gyro_cal\":\"%s\",\"gyro_bias_dps\":[%.2f,%.2f,%.2f],\"btn_presses\":%lu,\"btn_level\":%d,"
                   "\"upright\":[%.3f,%.3f,%.3f],\"upright_cal\":\"%s\",\"upright_t\":%llu,"
                   "\"upright_req\":\"%s\",\"upright_result\":\"%s\"}",
                   (unsigned long long)epochMs(), bat, WiFi.RSSI(),
                   (unsigned long)(millis() / 1000), FW_VERSION, (unsigned)ESP.getFreeHeap(), g.mpuOk ? "true" : "false",
                   g.bmpOk ? "true" : "false", g.ahtOk ? "true" : "false", eventCount(), (unsigned long)g.dropped,
                   g.gyroCalState == 2 ? "measured" : g.gyroCalState == 1 ? "nvs" : "none", g.gyroBiasDps[0],
                   g.gyroBiasDps[1], g.gyroBiasDps[2], (unsigned long)g.btnPresses, g.btnLevel ? 1 : 0,
                   g.upright[0], g.upright[1], g.upright[2],
                   g.uprightState == 2 ? "measured" : g.uprightState == 1 ? "nvs"
                   : g.uprightState == 3 ? "manual" : "default",
                   (unsigned long long)g.uprightT, g.uprightReq, g.uprightResult);
  if (n > 0) mqtt.publish(tStatus.c_str(), (const uint8_t*)buf, n, true);
  lastStatus = millis();
}

bool publishImu(const ImuPacket& p) {
  const bool replay = millis() - p.createdMs > REPLAY_AGE_MS;
  int n = snprintf(buf, sizeof(buf), "{\"v\":1,\"seq\":%lu,\"t0\":%llu,\"dt\":%d,\"replay\":%s", (unsigned long)p.seq,
                   (unsigned long long)p.t0, SAMPLE_PERIOD_MS, replay ? "true" : "false");
  static const char* keys[6] = {"ax", "ay", "az", "gx", "gy", "gz"};
  for (int k = 0; k < 6; k++) {
    n += snprintf(buf + n, sizeof(buf) - n, ",\"%s\":[", keys[k]);
    for (int i = 0; i < PACKET_SAMPLES; i++)
      n += snprintf(buf + n, sizeof(buf) - n, i ? ",%d" : "%d", p.v[k][i]);
    n += snprintf(buf + n, sizeof(buf) - n, "]");
  }
  n += snprintf(buf + n, sizeof(buf) - n, "}");
  return mqtt.publish(tImu.c_str(), (const uint8_t*)buf, n, false);
}

bool publishEnv(const EnvPacket& p) {
  int n = snprintf(buf, sizeof(buf), "{\"v\":1,\"seq\":%lu,\"t0\":%llu,\"dt\":%d,\"p_pa\":[", (unsigned long)p.seq,
                   (unsigned long long)p.t0, SAMPLE_PERIOD_MS * ENV_EVERY_SAMPLES);
  for (int i = 0; i < p.n; i++) n += snprintf(buf + n, sizeof(buf) - n, i ? ",%.1f" : "%.1f", p.p[i]);
  n += snprintf(buf + n, sizeof(buf) - n, "]");
  if (!isnan(p.temp_c)) n += snprintf(buf + n, sizeof(buf) - n, ",\"temp_c\":%.1f,\"rh\":%.1f", p.temp_c, p.rh);
  n += snprintf(buf + n, sizeof(buf) - n, "}");
  return mqtt.publish(tEnv.c_str(), (const uint8_t*)buf, n, false);
}

bool publishStoredEvent(const String&, const String& json) {
  return mqtt.publish(tEvent.c_str(), (const uint8_t*)json.c_str(), json.length(), false);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  String t(topic);
  if (t == tAck) {
    const char* id = doc["id"];
    if (id) eventAck(id);
  } else if (t == tDisplay) {
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    strlcpy(g.label, doc["label"] | "", sizeof(g.label));
    g.conf = doc["conf"].isNull() ? NAN : doc["conf"].as<float>();
    xSemaphoreGive(stateMutex);
  } else if (t == tCmd) {
    const char* cmd = doc["cmd"] | "";
    Serial.printf("[cmd] %s\n", cmd);
    if (!strcmp(cmd, "beep")) {
      buzzerPulse(doc["ms"] | 200);
    } else if (!strcmp(cmd, "set_upright")) {
      JsonArray a = doc["up"];
      if (a.size() == 3) {
        const float u[3] = {a[0] | 0.0f, a[1] | 0.0f, a[2] | 0.0f};
        setUpright(u);
      }
    } else if (!strcmp(cmd, "calibrate_upright")) {
      requestUprightCal(doc["id"] | "");  // người đeo đứng thẳng yên ~2 s; kết quả trong status
    } else if (!strcmp(cmd, "calibrate_gyro")) {
      requestGyroCal();  // đặt thiết bị nằm yên; kết quả in Serial và gửi trong status (gyro_cal, gyro_bias_dps)
    } else if (!strcmp(cmd, "display")) {
      xSemaphoreTake(stateMutex, portMAX_DELAY);
      strlcpy(g.mode, doc["mode"] | "monitor", sizeof(g.mode));
      strlcpy(g.activity, doc["activity"] | "", sizeof(g.activity));
      g.recordSinceMs = !strcmp(g.mode, "record") ? (millis() | 1) : 0;  // | 1: khác 0 cả khi millis() = 0
      xSemaphoreGive(stateMutex);
      displayWake();
    } else if (!strcmp(cmd, "set_threshold")) {
      FallParams& fp = fallDetector.params();
      fp.freefall_g = doc["freefall_g"] | fp.freefall_g;
      fp.freefall_ms = doc["freefall_ms"] | fp.freefall_ms;
      fp.impact_g = doc["impact_g"] | fp.impact_g;
      fp.impact_window_ms = doc["impact_window_ms"] | fp.impact_window_ms;
      fp.still_gyro_dps = doc["still_gyro_dps"] | fp.still_gyro_dps;
      fp.posture_deg = doc["posture_deg"] | fp.posture_deg;
      fp.still_delay_ms = doc["still_delay_ms"] | fp.still_delay_ms;
      saveThresholds();
      loadThresholds();
    } else if (!strcmp(cmd, "test_alarm")) {
      FallTrigger ft{epochMs(), 0.0f};
      xQueueSend(fallQueue, &ft, 0);
    } else if (!strcmp(cmd, "reboot")) {
      delay(200);
      ESP.restart();
    }
  }
}

bool mqttConnect() {
  if (!brokerKnown && !resolveBroker()) return false;
  mqtt.setServer(brokerIp, MQTT_PORT);
  Serial.printf("[mqtt] kết nối %s:%d …\n", brokerIp.toString().c_str(), MQTT_PORT);
  if (!mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASSWORD, tStatus.c_str(), 1, true, LWT)) {
    Serial.printf("[mqtt] lỗi, state=%d\n", mqtt.state());
    brokerKnown = false;  // thử giải tên lại lần sau
    return false;
  }
  mqtt.subscribe(tCmd.c_str(), 1);
  mqtt.subscribe(tDisplay.c_str(), 0);
  mqtt.subscribe(tAck.c_str(), 1);
  publishStatus();
  lastResend = 0;  // gửi lại ngay các sự kiện đang chờ
  Serial.println("[mqtt] đã kết nối");
  return true;
}

}  // namespace

void requestStatusNow() { statusRequested = true; }

void netTask(void*) {
  const String base = String("har/") + DEVICE_ID + "/";
  tImu = base + "imu";
  tEnv = base + "env";
  tEvent = base + "event";
  tStatus = base + "status";
  tCmd = base + "cmd";
  tDisplay = base + "display";
  tAck = base + "ack";

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // giảm trễ; tốn pin hơn một chút
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  mqtt.setBufferSize(MQTT_BUFFER_SIZE);
  mqtt.setKeepAlive(15);
  mqtt.setSocketTimeout(3);
  mqtt.setCallback(onMessage);

  for (;;) {
    // ngủ 10 ms, hoặc thức ngay khi có sự kiện mới (eventSave) để gửi không chờ chu kỳ 5 s
    if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10)) > 0) lastResend = 0;
    g.wifiUp = WiFi.status() == WL_CONNECTED;
    if (!g.wifiUp) {
      g.mqttUp = false;
      brokerKnown = false;
      continue;
    }
    g.rssi = WiFi.RSSI();
    if (!brokerKnown) resolveBroker();
    if (brokerKnown && ntpNeedsStart()) startNtp();
    g.timeSynced = timeValid();

    if (!mqtt.connected()) {
      g.mqttUp = false;
      if (millis() - lastAttempt > 2000) {
        lastAttempt = millis();
        mqttConnect();
      }
      continue;
    }
    g.mqttUp = true;
    mqtt.loop();

    // Xả dữ liệu cảm biến: xem trước, gửi được mới lấy khỏi hàng đợi
    for (int k = 0; k < MAX_PUBLISH_PER_LOOP; k++) {
      bool any = false;
      ImuPacket ip;
      if (xQueuePeek(imuQueue, &ip, 0) == pdTRUE) {
        if (!publishImu(ip)) break;
        xQueueReceive(imuQueue, &ip, 0);
        any = true;
      }
      EnvPacket ep;
      if (xQueuePeek(envQueue, &ep, 0) == pdTRUE) {
        if (!publishEnv(ep)) break;
        xQueueReceive(envQueue, &ep, 0);
        any = true;
      }
      if (!any) break;
      mqtt.loop();
    }

    if (millis() - lastResend > EVENT_RESEND_MS) {
      lastResend = millis();
      eventForEach(publishStoredEvent);
    }
    if (statusRequested || millis() - lastStatus > STATUS_PERIOD_MS) {
      statusRequested = false;
      publishStatus();
    }
  }
}
