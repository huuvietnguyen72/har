// Bảng chân ESP32 DevKit — giữ khớp với docs/pinout.md
#pragma once

// I2C bus 1: MPU6050 (0x68), AHT20 (0x38), BMP280 (0x76/0x77)
#define PIN_I2C1_SDA 21
#define PIN_I2C1_SCL 22

// I2C bus 2: OLED SSD1315 (0x3C)
#define PIN_I2C2_SDA 18
#define PIN_I2C2_SCL 19

#define PIN_BUZZER    25  // qua S8050
#define PIN_LED_GREEN 26
#define PIN_LED_RED   27
#define PIN_BUTTON    32  // INPUT_PULLUP, nhấn = LOW
#define PIN_VIBRATION 33  // tùy chọn
#define PIN_BATTERY   34  // cầu chia 100k/100k, chỉ đọc ADC
