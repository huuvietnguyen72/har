// pio test -e native  — chạy trên máy tính, không cần ESP32
#include <math.h>
#include <unity.h>

#include "button.h"
#include "fall_detector.h"
#include "gyro_cal.h"

void setUp() {}
void tearDown() {}

struct Sample { float ax, ay, az, gx, gy, gz; };

static int feed(FallDetector& d, uint64_t& t, Sample s, int n) {
  int hits = 0;
  for (int i = 0; i < n; i++, t += 20) hits += d.update(t, s.ax, s.ay, s.az, s.gx, s.gy, s.gz);
  return hits;
}

void test_fall_detected() {
  FallDetector d;
  uint64_t t = 1000;
  int hits = feed(d, t, {0, -1, 0, 0, 0, 0}, 50);       // đứng 1 s (Y chỉ xuống)
  hits += feed(d, t, {0.05f, -0.15f, 0.05f, 150, 80, 40}, 15);  // rơi tự do 0,3 s
  hits += feed(d, t, {2.5f, -2.0f, 2.0f, 200, 100, 50}, 4);     // va chạm ~3,8 g
  hits += feed(d, t, {1.0f, 0.05f, 0.05f, 1, 1, 1}, 150);       // nằm nghiêng 3 s
  TEST_ASSERT_EQUAL(1, hits);
  TEST_ASSERT_TRUE(d.peakG() > 2.5f);
  TEST_ASSERT_TRUE(d.tiltDeg() > 80);
}

void test_no_fall_when_landing_upright() {
  // ngồi phịch xuống ghế: có rơi + va chạm nhưng trục Y vẫn gần hướng xuống -> không báo
  FallDetector d;
  uint64_t t = 1000;
  int hits = feed(d, t, {0, -1, 0, 0, 0, 0}, 50);
  hits += feed(d, t, {0, -0.2f, 0, 20, 0, 0}, 6);
  hits += feed(d, t, {0, -2.8f, 0.4f, 30, 0, 0}, 3);
  hits += feed(d, t, {0, -0.9f, 0.3f, 1, 1, 1}, 150);  // nghiêng ~18°
  TEST_ASSERT_EQUAL(0, hits);
}

void test_no_fall_when_moving_after_impact() {
  FallDetector d;
  uint64_t t = 1000;
  int hits = feed(d, t, {0, -1, 0, 0, 0, 0}, 50);
  hits += feed(d, t, {0, -0.1f, 0, 0, 0, 0}, 10);
  hits += feed(d, t, {3, 0, 0, 0, 0, 0}, 3);
  for (int i = 0; i < 150; i++, t += 20) {  // đứng dậy đi tiếp: SVM dao động mạnh
    float s = 1.0f + 0.5f * sinf(i * 0.6f);
    hits += d.update(t, s, 0, 0, 60, 20, 10);
  }
  TEST_ASSERT_EQUAL(0, hits);
}

void test_walking_never_triggers() {
  FallDetector d;
  uint64_t t = 0;
  int hits = 0;
  for (int i = 0; i < 3000; i++, t += 20) {
    float ph = 2 * 3.14159f * 1.9f * i / 50.0f;
    hits += d.update(t, 0.1f * sinf(ph / 2), -1 + 0.35f * sinf(ph), 0.2f * sinf(ph + 1), 25 * sinf(ph), 10, 5);
  }
  TEST_ASSERT_EQUAL(0, hits);
}

static uint8_t run(Button& b, bool pressed, uint32_t& now, uint32_t ms) {
  uint8_t all = 0;
  for (uint32_t k = 0; k < ms; k += 10, now += 10) all |= b.update(pressed, now);
  return all;
}

void test_button_single_double_long() {
  Button b;
  uint32_t now = 0;
  uint8_t ev = run(b, true, now, 100) | run(b, false, now, 600);
  TEST_ASSERT_TRUE(ev & Button::PRESS);
  TEST_ASSERT_TRUE(ev & Button::SINGLE);
  TEST_ASSERT_FALSE(ev & Button::DOUBLE);

  ev = run(b, true, now, 100) | run(b, false, now, 150) | run(b, true, now, 100) | run(b, false, now, 600);
  TEST_ASSERT_TRUE(ev & Button::DOUBLE);
  TEST_ASSERT_FALSE(ev & Button::SINGLE);

  ev = run(b, true, now, 3200);
  TEST_ASSERT_TRUE(ev & Button::LONG);
  ev = run(b, false, now, 800);
  TEST_ASSERT_FALSE(ev & (Button::SINGLE | Button::DOUBLE));
}

void test_button_debounce() {
  Button b;
  uint32_t now = 0;
  uint8_t ev = 0;
  for (int i = 0; i < 10; i++) ev |= b.update(i % 2, now += 5);  // dội 5 ms
  ev |= run(b, false, now, 600);
  TEST_ASSERT_EQUAL(0, ev);
}

// --- Hiệu chỉnh con quay ---
// Mẫu thô: Y chỉ xuống (ay = -4096 LSB = -1 g), con quay = bias + nhiễu đối xứng -noise/0/+noise
// (trung bình đúng bằng 0 trên mỗi 3 mẫu, 75 mẫu chia hết cho 3)
static GyroCal::Result feedCal(GyroCal& c, int n, int16_t gx, int16_t gy, int16_t gz, int noise = 3,
                               int accWobble = 0) {
  GyroCal::Result r = GyroCal::PENDING;
  for (int i = 0; i < n; i++) {
    const int e = ((i % 3) - 1) * noise;
    const int16_t raw[6] = {0, (int16_t)(-4096 + ((i % 2) ? accWobble : -accWobble)), 0,
                            (int16_t)(gx + e), (int16_t)(gy - e), (int16_t)(gz + e / 2)};
    r = c.feed(raw);
    if (r != GyroCal::PENDING) return r;
  }
  return r;
}

void test_gyro_cal_still() {
  GyroCal c;
  c.start();
  // bias đo trên mạch thật: +13,8 / +4,2 / +0,4 °/s ≈ 904 / 275 / 26 LSB
  TEST_ASSERT_EQUAL(GyroCal::OK, feedCal(c, 75, 904, 275, 26));
  TEST_ASSERT_FALSE(c.active());
  TEST_ASSERT_INT_WITHIN(2, 904, c.bias()[0]);
  TEST_ASSERT_INT_WITHIN(2, 275, c.bias()[1]);
  TEST_ASSERT_INT_WITHIN(2, 26, c.bias()[2]);
  int16_t raw[6] = {0, -4096, 0, 904, 275, 26};
  c.apply(raw);
  TEST_ASSERT_INT_WITHIN(2, 0, raw[3]);
  TEST_ASSERT_INT_WITHIN(2, 0, raw[4]);
  TEST_ASSERT_INT_WITHIN(2, 0, raw[5]);
}

void test_gyro_cal_rejects_motion_then_retries() {
  GyroCal c;
  c.setBias(10, 20, 30);  // giá trị cũ từ NVS
  c.start();
  // đang cầm lắc: nhiễu con quay ±200 LSB (~3 °/s) -> bỏ cửa sổ, giữ bias cũ, vẫn chờ
  TEST_ASSERT_EQUAL(GyroCal::MOVING, feedCal(c, 75, 904, 275, 26, 200));
  TEST_ASSERT_TRUE(c.active());
  TEST_ASSERT_EQUAL(10, c.bias()[0]);
  // gia tốc dao động ±0,05 g dù con quay yên -> cũng bỏ
  TEST_ASSERT_EQUAL(GyroCal::MOVING, feedCal(c, 75, 904, 275, 26, 3, 205));
  TEST_ASSERT_EQUAL(20, c.bias()[1]);
  // cửa sổ sau nằm yên -> nhận
  TEST_ASSERT_EQUAL(GyroCal::OK, feedCal(c, 75, 904, 275, 26));
  TEST_ASSERT_INT_WITHIN(2, 904, c.bias()[0]);
}

void test_gyro_cal_rejects_steady_rotation() {
  GyroCal c;
  c.start();
  // quay đều 60 °/s (3930 LSB) quanh trục X: nhiễu nhỏ nhưng không phải bias
  TEST_ASSERT_EQUAL(GyroCal::OUT_OF_RANGE, feedCal(c, 75, 3930, 0, 0));
  TEST_ASSERT_EQUAL(0, c.bias()[0]);
  TEST_ASSERT_TRUE(c.active());
}

void test_gyro_cal_apply_saturates() {
  GyroCal c;
  c.setBias(-1000, 1000, 0);
  int16_t raw[6] = {0, 0, 0, 32000, -32000, 5};
  c.apply(raw);
  TEST_ASSERT_EQUAL(32767, raw[3]);
  TEST_ASSERT_EQUAL(-32768, raw[4]);
  TEST_ASSERT_EQUAL(5, raw[5]);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_fall_detected);
  RUN_TEST(test_no_fall_when_landing_upright);
  RUN_TEST(test_no_fall_when_moving_after_impact);
  RUN_TEST(test_walking_never_triggers);
  RUN_TEST(test_button_single_double_long);
  RUN_TEST(test_button_debounce);
  RUN_TEST(test_gyro_cal_still);
  RUN_TEST(test_gyro_cal_rejects_motion_then_retries);
  RUN_TEST(test_gyro_cal_rejects_steady_rotation);
  RUN_TEST(test_gyro_cal_apply_saturates);
  return UNITY_END();
}
