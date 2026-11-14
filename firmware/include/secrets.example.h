// Copy file này thành secrets.h rồi điền. KHÔNG commit secrets.h.
#pragma once

#define WIFI_SSID     "har-hotspot"
#define WIFI_PASSWORD "doi-mat-khau"

// Pi: tên mDNS (hargw.local), IP trong mạng hotspot, hoặc để "" để dùng IP gateway
// (khi Pi phát hotspot, gateway chính là Pi: 10.42.0.1).
#define MQTT_HOST     "hargw.local"
#define MQTT_PORT     1883
#define MQTT_USER     "har01"
#define MQTT_PASSWORD "doi-mat-khau"

// Máy chủ giờ: "" = dùng cùng địa chỉ với MQTT (chrony trên Pi)
#define NTP_HOST      ""

#define DEVICE_ID     "har01"
