// Khung tạm: chỉ nháy LED xanh để kiểm tra board và chân.
// Firmware thật sẽ thay thế theo danh sách việc trong firmware/README.md.
#include <Arduino.h>
#include "pins.h"

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_GREEN, OUTPUT);
  Serial.println("HAR firmware skeleton");
}

void loop() {
  digitalWrite(PIN_LED_GREEN, !digitalRead(PIN_LED_GREEN));
  delay(500);
}
