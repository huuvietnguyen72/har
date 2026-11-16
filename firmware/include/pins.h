// Bảng chân ESP32 DevKit theo mạch (đo trên thiết bị 17/11/2026) — giữ khớp với docs/pinout.md
#pragma once

// I2C bus 1 (bus duy nhất trên mạch): MPU6050 (0x68), board AHT20 + BMP280 (0x38 + 0x77), OLED (0x3C)
#define PIN_I2C1_SDA 21
#define PIN_I2C1_SCL 22

// I2C bus 2: không dùng trên mạch (GPIO19 là nút).
#define PIN_I2C2_SDA 18
#define PIN_I2C2_SCL 19

// OLED nằm trên bus nào: 1 = chung bus cảm biến GPIO21/22 (mạch hiện tại) — màn gửi từng dải 8 dòng có khóa
// i2cMutex để MPU6050 chen vào kịp; 2 = bus riêng GPIO18/19 (cần GPIO18/19 trống).
#define OLED_I2C_BUS 1

#define PIN_BUZZER    25  // loa qua tầng transistor; HIGH = kêu
#define PIN_LED_GREEN 26  // HIGH = sáng
#define PIN_LED_RED   27  // HIGH = sáng
// Nút: nối GND, INPUT_PULLUP, nhấn = LOW (dò bằng pin finder ngày 17/11/2026).
// GPIO19 trùng SCL của bus 2, nên khi nút ở 18/19 thì bus 2 không được bật.
#define PIN_BUTTON    19
#define PIN_VIBRATION 33  // không có motor rung trên mạch (USE_VIBRATION 0)
// Đo áp pin: mạch không có cầu chia áp, GPIO34 thả nổi -> readBattery() trả NAN, battery_v = null.
#define PIN_BATTERY   34

#define BUS2_PINS_FREE (PIN_BUTTON != PIN_I2C2_SDA && PIN_BUTTON != PIN_I2C2_SCL)
#if OLED_I2C_BUS == 2 && !BUS2_PINS_FREE
#error "OLED_I2C_BUS = 2 nhưng PIN_BUTTON trùng chân bus 2 (GPIO18/19)"
#endif
