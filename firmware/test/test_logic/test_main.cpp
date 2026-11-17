// pio test -e native  — chạy trên máy tính, không cần ESP32
#include <math.h>
#include <unity.h>

#include "button.h"
#include "fall_detector.h"
#include "gyro_cal.h"
#include "upright_cal.h"

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
  int hits = feed(d, t, {-1, 0, 0, 0, 0, 0}, 50);       // đứng 1 s (X chỉ xuống)
  hits += feed(d, t, {-0.15f, -0.05f, 0.05f, 80, -150, 40}, 15);  // rơi tự do 0,3 s
  hits += feed(d, t, {-2.0f, -2.5f, 2.0f, 100, -200, 50}, 4);     // va chạm ~3,8 g
  hits += feed(d, t, {0.05f, -1.0f, 0.05f, 1, -1, 1}, 150);       // nằm nghiêng 3 s
  TEST_ASSERT_EQUAL(1, hits);
  TEST_ASSERT_TRUE(d.peakG() > 2.5f);
  TEST_ASSERT_TRUE(d.tiltDeg() > 80);
}

// Cú ngã trước thật (17/11/2026): người đổ xoay nên SVM < 0,4 g chỉ 2 mẫu (~40 ms), dưới 0,6 g 5 mẫu;
// va chạm 3,5 g; còn nảy/chỉnh ~1,5 s (con quay ~80 °/s) rồi mới nằm yên. Ngưỡng cũ (0,4 g / 80 ms / xét yên
// ở giây 1–2) bỏ lọt; ngưỡng mặc định hiện tại phải bắt được.
static int realForwardFall(FallDetector& d) {
  uint64_t t = 1000;
  int h = feed(d, t, {-1, 0, 0, 0, 0, 0}, 50);                    // đứng
  h += feed(d, t, {-0.75f, 0.1f, -0.2f, 10, 60, 30}, 10);         // bắt đầu đổ người
  h += feed(d, t, {-0.5f, 0.1f, -0.2f, 10, 80, 30}, 3);           // ~0,55 g
  h += feed(d, t, {-0.15f, 0.1f, -0.15f, 20, 80, 30}, 2);         // ~0,23 g, 40 ms
  h += feed(d, t, {-0.3f, 0.3f, 0.9f, 50, 300, 100}, 5);          // xoay người ~1 g
  h += feed(d, t, {0.5f, 0.6f, 3.4f, 100, 300, 100}, 4);          // va chạm ~3,5 g
  h += feed(d, t, {0.2f, 0.3f, 1.3f, 20, 80, 40}, 40);            // nảy, chỉnh trên nệm 0,8 s
  for (int i = 0; i < 35; i++, t += 20)                           // còn cử động ~0,7 s (70% yên)
    h += d.update(t, 0.1f, 0.25f, (i % 3) ? 1.0f : 1.25f, 5, (i % 3) ? 10.0f : 80.0f, 5);
  h += feed(d, t, {0.1f, 0.25f, 1.0f, 1, 1, 1}, 150);             // nằm sấp yên 3 s
  return h;
}

void test_real_forward_fall_detected() {
  FallDetector d;
  TEST_ASSERT_EQUAL(1, realForwardFall(d));
  FallDetector old;
  old.params().freefall_g = 0.4f;
  old.params().freefall_ms = 80;
  old.params().still_delay_ms = 2000;
  TEST_ASSERT_EQUAL(0, realForwardFall(old));
}

void test_no_fall_when_landing_upright() {
  // ngồi phịch xuống ghế: có rơi + va chạm nhưng trục X vẫn gần hướng xuống -> không báo
  FallDetector d;
  uint64_t t = 1000;
  int hits = feed(d, t, {-1, 0, 0, 0, 0, 0}, 50);
  hits += feed(d, t, {-0.2f, 0, 0, 0, -20, 0}, 6);
  hits += feed(d, t, {-2.8f, 0, 0.4f, 0, -30, 0}, 3);
  hits += feed(d, t, {-0.9f, 0, 0.3f, 1, -1, 1}, 150);  // nghiêng ~18°
  TEST_ASSERT_EQUAL(0, hits);
}

void test_no_fall_when_moving_after_impact() {
  FallDetector d;
  uint64_t t = 1000;
  int hits = feed(d, t, {-1, 0, 0, 0, 0, 0}, 50);
  hits += feed(d, t, {-0.1f, 0, 0, 0, 0, 0}, 10);
  hits += feed(d, t, {0, -3, 0, 0, 0, 0}, 3);
  for (int i = 0; i < 150; i++, t += 20) {  // đứng dậy đi tiếp: SVM dao động mạnh
    float s = 1.0f + 0.5f * sinf(i * 0.6f);
    hits += d.update(t, 0, -s, 0, 20, -60, 10);
  }
  TEST_ASSERT_EQUAL(0, hits);
}

void test_walking_never_triggers() {
  FallDetector d;
  uint64_t t = 0;
  int hits = 0;
  for (int i = 0; i < 3000; i++, t += 20) {
    float ph = 2 * 3.14159f * 1.9f * i / 50.0f;
    hits += d.update(t, -1 + 0.35f * sinf(ph), -0.1f * sinf(ph / 2), 0.2f * sinf(ph + 1), 10, -25 * sinf(ph), 5);
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
// Mẫu thô: X chỉ xuống (ax = -4096 LSB = -1 g), con quay = bias + nhiễu đối xứng -noise/0/+noise
// (trung bình đúng bằng 0 trên mỗi 3 mẫu, 75 mẫu chia hết cho 3)
static GyroCal::Result feedCal(GyroCal& c, int n, int16_t gx, int16_t gy, int16_t gz, int noise = 3,
                               int accWobble = 0) {
  GyroCal::Result r = GyroCal::PENDING;
  for (int i = 0; i < n; i++) {
    const int e = ((i % 3) - 1) * noise;
    const int16_t raw[6] = {(int16_t)(-4096 + ((i % 2) ? accWobble : -accWobble)), 0, 0,
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
  int16_t raw[6] = {-4096, 0, 0, 904, 275, 26};
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

// --- Hiệu chỉnh hướng đứng thẳng ---
static UprightCal::Result feedUp(UprightCal& c, int n, float ax, float ay, float az, float wobble = 0.005f,
                                 float gyro = 2.0f) {
  UprightCal::Result r = UprightCal::PENDING;
  for (int i = 0; i < n; i++) {
    const float e = ((i % 3) - 1) * wobble;  // lắc nhẹ khi đứng
    r = c.feed(ax + e, ay, az - e, gyro, -gyro, 0);
    if (r != UprightCal::PENDING) return r;
  }
  return r;
}

void test_upright_tilted_wear() {
  // hộp cài nghiêng 20° quanh trục Y: đứng thẳng đọc (-cos20, 0, -sin20)
  UprightCal c;
  c.start();
  TEST_ASSERT_EQUAL(UprightCal::OK, feedUp(c, 100, -0.940f, 0, -0.342f));
  TEST_ASSERT_FALSE(c.active());
  const float def[3] = {-1, 0, 0};
  TEST_ASSERT_FLOAT_WITHIN(1.0f, 20.0f, UprightCal::angleDeg(c.up(), def));
  TEST_ASSERT_FLOAT_WITHIN(0.01f, -0.940f, c.up()[0]);
}

void test_upright_upside_down_accepted() {
  // đeo ngược (X chỉ lên): thư viện vẫn nhận, record.py sẽ hỏi xác nhận vì lệch 180°
  UprightCal c;
  c.start();
  TEST_ASSERT_EQUAL(UprightCal::OK, feedUp(c, 100, 1.0f, 0, 0));
  const float def[3] = {-1, 0, 0};
  TEST_ASSERT_FLOAT_WITHIN(1.0f, 180.0f, UprightCal::angleDeg(c.up(), def));
}

void test_upright_rejects_moving_and_bad_gravity() {
  UprightCal c;
  c.start();
  TEST_ASSERT_EQUAL(UprightCal::MOVING, feedUp(c, 100, -1.0f, 0, 0, 0.15f));     // đi bộ: SVM dao động 0,3 g
  TEST_ASSERT_EQUAL(UprightCal::MOVING, feedUp(c, 100, -1.0f, 0, 0, 0.005f, 40));  // xoay người
  TEST_ASSERT_EQUAL(UprightCal::BAD_GRAVITY, feedUp(c, 100, -0.5f, 0, 0));       // không phải 1 g
  TEST_ASSERT_TRUE(c.active());
  TEST_ASSERT_EQUAL(UprightCal::OK, feedUp(c, 100, -1.0f, 0, 0));
}

void test_fall_uses_calibrated_upright() {
  // Hộp đeo nghiêng 40°. Sau va chạm người đeo nằm yên ở tư thế lệch 15° so với lúc đứng (55° so với
  // hướng mặc định). Theo hướng đã hiệu chỉnh: chưa đổi tư thế -> không báo. Theo mặc định: báo nhầm.
  const float c40 = 0.766f, s40 = 0.643f, c55 = 0.574f, s55 = 0.819f;
  int hits[2];
  for (int k = 0; k < 2; k++) {
    FallDetector d;
    if (k == 0) {
      d.params().up_x = -c40;
      d.params().up_y = 0;
      d.params().up_z = -s40;
    }
    uint64_t t = 1000;
    int h = feed(d, t, {-c40, 0, -s40, 0, 0, 0}, 50);
    h += feed(d, t, {-0.15f, -0.05f, 0.05f, 80, -150, 40}, 15);
    h += feed(d, t, {-2.0f, -2.5f, 2.0f, 100, -200, 50}, 4);
    h += feed(d, t, {-c55, 0, -s55, 1, -1, 1}, 150);
    hits[k] = h;
  }
  TEST_ASSERT_EQUAL(0, hits[0]);
  TEST_ASSERT_EQUAL(1, hits[1]);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_fall_detected);
  RUN_TEST(test_real_forward_fall_detected);
  RUN_TEST(test_no_fall_when_landing_upright);
  RUN_TEST(test_no_fall_when_moving_after_impact);
  RUN_TEST(test_walking_never_triggers);
  RUN_TEST(test_button_single_double_long);
  RUN_TEST(test_button_debounce);
  RUN_TEST(test_gyro_cal_still);
  RUN_TEST(test_gyro_cal_rejects_motion_then_retries);
  RUN_TEST(test_gyro_cal_rejects_steady_rotation);
  RUN_TEST(test_gyro_cal_apply_saturates);
  RUN_TEST(test_upright_tilted_wear);
  RUN_TEST(test_upright_upside_down_accepted);
  RUN_TEST(test_upright_rejects_moving_and_bad_gravity);
  RUN_TEST(test_fall_uses_calibrated_upright);
  return UNITY_END();
}
