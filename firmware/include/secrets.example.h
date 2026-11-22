// Copy file này thành secrets.h rồi điền. KHÔNG commit secrets.h.
#pragma once

#define WIFI_SSID     "har-hotspot"
#define WIFI_PASSWORD "doi-mat-khau"

// Tùy chọn: mạng thứ 2, 3 (ví dụ hotspot iPhone để demo ngoài nhà). Bộ đeo chọn theo thứ tự ưu tiên:
// WIFI_SSID trước, rồi _2, _3; mất Wi-Fi quá 20 s thì quét lại. MQTT_HOST_n là địa chỉ Pi trong mạng đó
// (bỏ trống thì dùng MQTT_HOST). Hotspot iPhone: bật "Tối đa hóa tương thích" (2,4 GHz), Pi đặt IP cố định
// 172.20.10.14 (docs/van-hanh.md, mục Hotspot iPhone).
// #define WIFI_SSID_2     "iPhone-HAR"
// #define WIFI_PASSWORD_2 "doi-mat-khau"
// #define MQTT_HOST_2     "172.20.10.14"

// Pi: tên mDNS (hargw.local), IP trong mạng hotspot, hoặc để "" để dùng IP gateway
// (khi Pi phát hotspot, gateway chính là Pi: 10.42.0.1).
#define MQTT_HOST     "hargw.local"
#define MQTT_PORT     1883
#define MQTT_USER     "har01"
#define MQTT_PASSWORD "doi-mat-khau"

// Máy chủ giờ: "" = dùng cùng địa chỉ với MQTT (chrony trên Pi)
#define NTP_HOST      ""

#define DEVICE_ID     "har01"
