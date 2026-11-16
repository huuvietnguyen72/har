// Cảm biến trên bus I2C 1 (GPIO21/22, 400 kHz):
//   MPU6050 (0x68) — driver thanh ghi trực tiếp để lấy giá trị thô int16, ±8 g, ±500 °/s, DLPF 21 Hz
//   BMP280 (0x76/0x77) — thư viện Adafruit, normal mode, oversampling áp ×16, IIR ×4
//   AHT20 (0x38) — driver trực tiếp, chia lệnh đo và đọc để không giữ bus 80 ms
#include <Adafruit_BMP280.h>
#include <Preferences.h>
#include <Wire.h>

#include "app.h"
#include "gyro_cal.h"
#include "pins.h"
#include "upright_cal.h"

namespace {

constexpr uint8_t MPU_ADDR = 0x68;
constexpr uint8_t AHT_ADDR = 0x38;
Adafruit_BMP280 bmp(&Wire);

// Hiệu chỉnh con quay: chỉ samplerTask đụng vào gyroCal; các task khác giao tiếp qua cờ volatile
GyroCal gyroCal;
volatile bool gyroCalRequest = false;            // netTask -> samplerTask
volatile uint8_t gyroCalReport = 0;              // samplerTask -> slowTask: 1 = đạt (lưu NVS), 2 = bỏ cuộc
volatile int16_t gyroCalBiasRaw[3] = {0, 0, 0};  // bias vừa đo, để slowTask lưu NVS

// Hướng đứng thẳng: chỉ samplerTask đụng vào uprightCal và fallDetector.params().up_*
UprightCal uprightCal;
volatile bool uprightRequest = false;  // netTask -> samplerTask
volatile uint8_t uprightReport = 0;    // samplerTask -> slowTask: 1 = đạt, 2 = đang cử động, 3 = sai 1 g

void loadGyroBias() {
  Preferences p;
  p.begin("imu", true);
  if (p.isKey("gbx")) {
    gyroCal.setBias(p.getShort("gbx", 0), p.getShort("gby", 0), p.getShort("gbz", 0));
    g.gyroCalState = 1;
  }
  p.end();
  for (int k = 0; k < 3; k++) g.gyroBiasDps[k] = gyroCal.biasDps(k);
}

void loadUpright() {
  FallParams& fp = fallDetector.params();
  Preferences p;
  p.begin("imu", true);
  if (p.isKey("upx")) {
    fp.up_x = p.getFloat("upx", fp.up_x);
    fp.up_y = p.getFloat("upy", fp.up_y);
    fp.up_z = p.getFloat("upz", fp.up_z);
    g.uprightState = 1;
  }
  p.end();
  g.upright[0] = fp.up_x;
  g.upright[1] = fp.up_y;
  g.upright[2] = fp.up_z;
}

void saveUpright(const float u[3]) {
  Preferences p;
  p.begin("imu", false);
  p.putFloat("upx", u[0]);
  p.putFloat("upy", u[1]);
  p.putFloat("upz", u[2]);
  p.end();
}

void saveGyroBias(const int16_t b[3]) {
  Preferences p;
  p.begin("imu", false);
  p.putShort("gbx", b[0]);
  p.putShort("gby", b[1]);
  p.putShort("gbz", b[2]);
  p.end();
}

bool writeReg(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool readRegs(uint8_t addr, uint8_t reg, uint8_t* buf, size_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, (int)n) != (int)n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

bool mpuInit() {
  uint8_t who = 0;
  if (!readRegs(MPU_ADDR, 0x75, &who, 1)) return false;
  if (who != 0x68) Serial.printf("[mpu] WHO_AM_I=0x%02X (bản clone?), vẫn thử dùng\n", who);
  writeReg(MPU_ADDR, 0x6B, 0x80);  // reset
  delay(100);
  bool ok = writeReg(MPU_ADDR, 0x6B, 0x01)      // đồng hồ PLL theo gyro X
            && writeReg(MPU_ADDR, 0x19, 0x04)   // SMPLRT_DIV: 1 kHz / 5 = 200 Hz nội bộ
            && writeReg(MPU_ADDR, 0x1A, 0x04)   // DLPF 21 Hz (accel) / 20 Hz (gyro)
            && writeReg(MPU_ADDR, 0x1B, 0x08)   // ±500 °/s
            && writeReg(MPU_ADDR, 0x1C, 0x10);  // ±8 g
  delay(50);
  return ok;
}

// raw[0..5] = ax, ay, az, gx, gy, gz
bool mpuRead(int16_t raw[6]) {
  uint8_t b[14];
  if (!readRegs(MPU_ADDR, 0x3B, b, 14)) return false;
  raw[0] = (int16_t)(b[0] << 8 | b[1]);
  raw[1] = (int16_t)(b[2] << 8 | b[3]);
  raw[2] = (int16_t)(b[4] << 8 | b[5]);
  raw[3] = (int16_t)(b[8] << 8 | b[9]);  // bỏ qua nhiệt độ ở b[6..7]
  raw[4] = (int16_t)(b[10] << 8 | b[11]);
  raw[5] = (int16_t)(b[12] << 8 | b[13]);
  return true;
}

bool bmpInit() {
  if (!bmp.begin(0x76) && !bmp.begin(0x77)) return false;
  bmp.setSampling(Adafruit_BMP280::MODE_NORMAL, Adafruit_BMP280::SAMPLING_X2, Adafruit_BMP280::SAMPLING_X16,
                  Adafruit_BMP280::FILTER_X4, Adafruit_BMP280::STANDBY_MS_1);
  return true;
}

bool ahtInit() {
  uint8_t st = 0;
  Wire.beginTransmission(AHT_ADDR);
  if (Wire.endTransmission() != 0) return false;
  delay(40);
  if (Wire.requestFrom((int)AHT_ADDR, 1) == 1) st = Wire.read();
  if (!(st & 0x08)) {  // chưa hiệu chuẩn
    Wire.beginTransmission(AHT_ADDR);
    Wire.write(0xBE);
    Wire.write(0x08);
    Wire.write(0x00);
    Wire.endTransmission();
    delay(10);
  }
  return true;
}

bool ahtTrigger() {
  Wire.beginTransmission(AHT_ADDR);
  Wire.write(0xAC);
  Wire.write(0x33);
  Wire.write(0x00);
  return Wire.endTransmission() == 0;
}

bool ahtRead(float& temp, float& rh) {
  uint8_t b[7];
  if (Wire.requestFrom((int)AHT_ADDR, 7) != 7) return false;
  for (int i = 0; i < 7; i++) b[i] = Wire.read();
  if (b[0] & 0x80) return false;  // vẫn đang đo
  uint32_t h = ((uint32_t)b[1] << 12) | ((uint32_t)b[2] << 4) | (b[3] >> 4);
  uint32_t t = (((uint32_t)b[3] & 0x0F) << 16) | ((uint32_t)b[4] << 8) | b[5];
  rh = h * 100.0f / 1048576.0f;
  temp = t * 200.0f / 1048576.0f - 50.0f;
  return true;
}

// NAN = không đo được pin: mạch hiện tại không nối áp pin vào GPIO34 (chân thả nổi, đọc ~0,3 V)
// không có pin. Dưới 2,5 V thì Li-ion đã hỏng/ngắt bảo vệ, nên coi như không có pin.
float readBattery() {
  uint32_t mv = 0;
  for (int i = 0; i < 16; i++) mv += analogReadMilliVolts(PIN_BATTERY);
  const float v = (mv / 16.0f) / 1000.0f * BATTERY_DIVIDER * BATTERY_CAL;
  return v < BATTERY_PRESENT_V ? NAN : v;
}

}  // namespace

bool sensorsBegin() {
  Wire.begin(PIN_I2C1_SDA, PIN_I2C1_SCL, 400000);
  analogSetPinAttenuation(PIN_BATTERY, ADC_11db);
  g.mpuOk = mpuInit();
  g.bmpOk = bmpInit();
  g.ahtOk = ahtInit();
  g.battery_v = readBattery();
  Serial.printf("[sensors] MPU6050=%d BMP280=%d AHT20=%d pin=%.2f V\n", g.mpuOk, g.bmpOk, g.ahtOk, g.battery_v);
  gyroCal.params().lsb_per_dps = GYRO_LSB_PER_DPS;
  gyroCal.params().lsb_per_g = ACC_LSB_PER_G;
  loadGyroBias();
  Serial.printf("[gyro] bias %s: %.2f %.2f %.2f °/s — đo lại khi nằm yên 1,5 s\n",
                g.gyroCalState ? "NVS" : "chưa có", g.gyroBiasDps[0], g.gyroBiasDps[1], g.gyroBiasDps[2]);
  gyroCalRequest = true;  // samplerTask đo ngay khi bắt đầu
  loadUpright();
  Serial.printf("[upright] %s: %.3f %.3f %.3f\n", g.uprightState ? "NVS" : "mặc định", g.upright[0],
                g.upright[1], g.upright[2]);
  return g.mpuOk;
}

void samplerTask(void*) {
  ImuPacket pk{};
  EnvPacket ep{};
  uint8_t i = 0;
  uint32_t seq = 0, envSeq = 0, n = 0, fails = 0;
  int calTries = 0, upTries = 0;
  int16_t raw[6] = {0, (int16_t)-ACC_LSB_PER_G, 0, 0, 0, 0};  // thô từ MPU6050
  int16_t cr[6];                                              // đã trừ bias con quay
  TickType_t last = xTaskGetTickCount();

  for (;;) {
    vTaskDelayUntil(&last, pdMS_TO_TICKS(SAMPLE_PERIOD_MS));
    const uint32_t nowMs = millis();
    bool ok = false;
    float pressure = NAN;
    const bool envTick = (n % ENV_EVERY_SAMPLES) == 0;

    if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(8)) == pdTRUE) {
      ok = mpuRead(raw);
      if (envTick && g.bmpOk) pressure = bmp.readPressure();
      xSemaphoreGive(i2cMutex);
    }
    if (!ok) {  // giữ nhịp 50 Hz: lặp lại mẫu trước, thử khởi tạo lại sau 1 s lỗi liên tục
      g.imuMiss++;
      if (++fails >= 50) {
        g.mpuOk = false;
        if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
          g.mpuOk = mpuInit();
          xSemaphoreGive(i2cMutex);
        }
        fails = 0;
      }
    } else {
      fails = 0;
      g.mpuOk = true;
    }
    n++;
    g.samples = n;

    // Hiệu chỉnh con quay: chỉ cho ăn mẫu đọc thật (mẫu lặp khi lỗi sẽ làm sai thống kê)
    if (gyroCalRequest) {
      gyroCalRequest = false;
      calTries = 0;
      gyroCal.start();
    }
    if (ok && gyroCal.active()) {
      const GyroCal::Result r = gyroCal.feed(raw);
      if (r == GyroCal::OK) {
        for (int k = 0; k < 3; k++) {
          gyroCalBiasRaw[k] = gyroCal.bias()[k];
          g.gyroBiasDps[k] = gyroCal.biasDps(k);
        }
        g.gyroCalState = 2;
        gyroCalReport = 1;
      } else if (r != GyroCal::PENDING && ++calTries >= GYRO_CAL_TRIES) {
        gyroCal.stop();
        gyroCalReport = 2;
      }
    }
    memcpy(cr, raw, sizeof(cr));
    gyroCal.apply(cr);

    // Bộ phát hiện té chạy với thời gian millis() (đơn điệu), đổi sang epoch khi báo
    const float ax = cr[0] / ACC_LSB_PER_G, ay = cr[1] / ACC_LSB_PER_G, az = cr[2] / ACC_LSB_PER_G;
    const float gx = cr[3] / GYRO_LSB_PER_DPS, gy = cr[4] / GYRO_LSB_PER_DPS, gz = cr[5] / GYRO_LSB_PER_DPS;
    // Hiệu chỉnh hướng đứng thẳng (theo lệnh): người đeo đứng thẳng yên ~2 s
    if (uprightRequest) {
      uprightRequest = false;
      upTries = 0;
      uprightCal.start();
    }
    if (ok && uprightCal.active()) {
      const UprightCal::Result r = uprightCal.feed(ax, ay, az, gx, gy, gz);
      if (r == UprightCal::OK) {
        FallParams& fp = fallDetector.params();
        fp.up_x = uprightCal.up()[0];
        fp.up_y = uprightCal.up()[1];
        fp.up_z = uprightCal.up()[2];
        for (int k = 0; k < 3; k++) g.upright[k] = uprightCal.up()[k];
        g.uprightState = 2;
        g.uprightT = timeValid() ? epochMs() : 0;
        uprightReport = 1;
      } else if (r != UprightCal::PENDING && ++upTries >= UPRIGHT_CAL_TRIES) {
        uprightCal.stop();
        uprightReport = r == UprightCal::MOVING ? 2 : 3;
      }
    }

    if (fallDetector.update(nowMs, ax, ay, az, gx, gy, gz)) {
      FallTrigger ft;
      const uint64_t ageMs = nowMs - fallDetector.impactMs();
      ft.t = timeValid() ? epochMs() - ageMs : fallDetector.impactMs();
      ft.peak_g = fallDetector.peakG();
      xQueueSend(fallQueue, &ft, 0);
    }

    if (!timeValid()) continue;  // chưa có giờ từ Pi: chưa đóng gói dữ liệu

    if (i == 0) {
      pk.t0 = epochMs();
      pk.seq = seq;
    }
    for (int k = 0; k < 6; k++) pk.v[k][i] = cr[k];
    if (++i >= PACKET_SAMPLES) {
      pk.createdMs = millis();
      if (xQueueSend(imuQueue, &pk, 0) != pdTRUE) {  // đầy (mất mạng > 60 s): bỏ gói cũ nhất
        ImuPacket old;
        xQueueReceive(imuQueue, &old, 0);
        xQueueSend(imuQueue, &pk, 0);
        g.dropped++;
      }
      seq++;
      i = 0;
    }

    if (envTick && !isnan(pressure)) {
      if (ep.n == 0) {
        ep.t0 = epochMs();
        ep.seq = envSeq;
      }
      ep.p[ep.n++] = pressure;
      if (ep.n >= ENV_PACKET_SAMPLES) {
        ep.temp_c = NAN;
        ep.rh = NAN;
        if (g.thFresh) {
          ep.temp_c = g.temp_c;
          ep.rh = g.rh;
          g.thFresh = false;
        }
        ep.createdMs = millis();
        if (xQueueSend(envQueue, &ep, 0) != pdTRUE) {
          EnvPacket old;
          xQueueReceive(envQueue, &old, 0);
          xQueueSend(envQueue, &ep, 0);
        }
        envSeq++;
        ep.n = 0;
      }
    }
  }
}

void requestGyroCal() { gyroCalRequest = true; }

bool setUpright(const float u[3]) {
  const float n = sqrtf(u[0] * u[0] + u[1] * u[1] + u[2] * u[2]);
  if (!(n > 0.5f && n < 2.0f)) return false;
  FallParams& fp = fallDetector.params();  // float ghi đơn lẻ, samplerTask đọc lại ở mẫu sau
  fp.up_x = u[0] / n;
  fp.up_y = u[1] / n;
  fp.up_z = u[2] / n;
  g.upright[0] = fp.up_x;
  g.upright[1] = fp.up_y;
  g.upright[2] = fp.up_z;
  g.uprightState = 3;
  saveUpright(g.upright);
  Serial.printf("[upright] đặt tay: %.3f %.3f %.3f (lưu NVS)\n", g.upright[0], g.upright[1], g.upright[2]);
  requestStatusNow();
  return true;
}

void requestUprightCal(const char* id) {
  strlcpy(g.uprightReq, id, sizeof(g.uprightReq));
  strlcpy(g.uprightResult, "pending", sizeof(g.uprightResult));
  uprightRequest = true;
  requestStatusNow();
}

// Báo kết quả hiệu chỉnh hướng đứng thẳng (ghi NVS, in Serial, gửi status) ngoài samplerTask
void reportUpright() {
  const uint8_t rep = uprightReport;
  if (!rep) return;
  uprightReport = 0;
  if (rep == 1) {
    const float u[3] = {g.upright[0], g.upright[1], g.upright[2]};
    saveUpright(u);
    strlcpy(g.uprightResult, "ok", sizeof(g.uprightResult));
    Serial.printf("[upright] đã hiệu chỉnh: %.3f %.3f %.3f (lưu NVS)\n", u[0], u[1], u[2]);
  } else {
    strlcpy(g.uprightResult, rep == 2 ? "moving" : "bad_gravity", sizeof(g.uprightResult));
    Serial.printf("[upright] không đạt (%s), giữ hướng cũ\n", g.uprightResult);
  }
  requestStatusNow();
}

// Báo kết quả hiệu chỉnh con quay (in Serial, ghi NVS) ngoài samplerTask để không làm trễ nhịp 50 Hz
void reportGyroCal() {
  const uint8_t rep = gyroCalReport;
  if (!rep) return;
  gyroCalReport = 0;
  if (rep == 1) {
    const int16_t b[3] = {gyroCalBiasRaw[0], gyroCalBiasRaw[1], gyroCalBiasRaw[2]};
    saveGyroBias(b);
    Serial.printf("[gyro] đã hiệu chỉnh: bias %.2f %.2f %.2f °/s (lưu NVS)\n", g.gyroBiasDps[0], g.gyroBiasDps[1],
                  g.gyroBiasDps[2]);
  } else {
    Serial.printf("[gyro] không nằm yên đủ lâu trong %d s, giữ bias %s\n", GYRO_CAL_TRIES * 3 / 2,
                  g.gyroCalState ? "NVS" : "0 (chưa hiệu chỉnh)");
  }
  requestStatusNow();
}

void slowTask(void*) {
  uint32_t lastSlow = 0;
  bool first = true;
  for (;;) {
    reportGyroCal();
    reportUpright();
    if (!first && millis() - lastSlow < SLOW_PERIOD_MS) {
      vTaskDelay(pdMS_TO_TICKS(250));
      continue;
    }
    first = false;
    lastSlow = millis();
    if (g.ahtOk) {
      bool trig = false;
      if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        trig = ahtTrigger();
        xSemaphoreGive(i2cMutex);
      }
      vTaskDelay(pdMS_TO_TICKS(85));  // AHT20 đo ~80 ms, không giữ bus
      float t, h;
      if (trig && xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        bool ok = ahtRead(t, h);
        xSemaphoreGive(i2cMutex);
        if (ok) {
          g.temp_c = t;
          g.rh = h;
          g.thFresh = true;
        }
      }
    }
    const float v = readBattery();
    g.battery_v = (isnan(g.battery_v) || isnan(v)) ? v : 0.7f * g.battery_v + 0.3f * v;  // làm mượt
  }
}
