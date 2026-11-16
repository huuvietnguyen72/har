// Bảng chân ESP32 DevKit — giữ khớp với docs/pinout.md
#pragma once

// I2C bus 1: MPU6050 (0x68), AHT20 (0x38), BMP280 (0x76/0x77)
#define PIN_I2C1_SDA 21
#define PIN_I2C1_SCL 22

// I2C bus 2: OLED SSD1315 (0x3C)
#define PIN_I2C2_SDA 18
#define PIN_I2C2_SCL 19

// OLED nằm trên bus nào: 2 = bus riêng GPIO18/19 (thiết kế, không ảnh hưởng nhịp 50 Hz);
// 1 = chung bus cảm biến GPIO21/22 — màn gửi từng dải 8 dòng có khóa i2cMutex để MPU6050 chen vào kịp.
#define OLED_I2C_BUS 1

#define PIN_BUZZER    25  // qua S8050
#define PIN_LED_GREEN 26
#define PIN_LED_RED   27
// Nút: INPUT_PULLUP, nhấn = LOW. Thiết kế là GPIO32; mạch hiện tại nút cắm GPIO19 (dò bằng pin finder
// ngày 17/11/2026). GPIO19 trùng SCL của bus 2, nên khi nút ở 18/19 thì bus 2 không được bật.
#define PIN_BUTTON    19
#define PIN_VIBRATION 33  // tùy chọn
#define PIN_BATTERY   34  // cầu chia 100k/100k, chỉ đọc ADC

#define BUS2_PINS_FREE (PIN_BUTTON != PIN_I2C2_SDA && PIN_BUTTON != PIN_I2C2_SCL)
#if OLED_I2C_BUS == 2 && !BUS2_PINS_FREE
#error "OLED_I2C_BUS = 2 nhưng PIN_BUTTON trùng chân bus 2 (GPIO18/19)"
#endif
