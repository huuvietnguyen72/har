// Chọn mạng Wi-Fi theo thứ tự ưu tiên — C++ thuần, test được trên máy tính (pio test -e native).
//
// Bộ đeo lưu tối đa vài mạng (secrets.h: WIFI_SSID, WIFI_SSID_2, WIFI_SSID_3), ví dụ Wi-Fi nhà rồi hotspot
// iPhone. Pi đặt cùng thứ tự ưu tiên (NetworkManager autoconnect-priority), nên khi cả hai mạng cùng có sóng
// thì bộ đeo và Pi vào cùng một mạng. Chọn theo thứ tự cấu hình, không theo sóng mạnh nhất (WiFiMulti chọn
// theo sóng, có thể làm bộ đeo vào hotspot trong khi Pi ở Wi-Fi nhà).
#pragma once
#include <string.h>

// configured: tên mạng theo thứ tự ưu tiên (NULL hoặc "" = ô trống, bỏ qua).
// visible: các tên mạng quét được. Trả về chỉ số mạng ưu tiên cao nhất đang có sóng, -1 nếu không có mạng nào.
inline int pickNetwork(const char* const* configured, int n, const char* const* visible, int m) {
  for (int i = 0; i < n; i++) {
    if (!configured[i] || !configured[i][0]) continue;
    for (int j = 0; j < m; j++) {
      if (visible[j] && strcmp(configured[i], visible[j]) == 0) return i;
    }
  }
  return -1;
}

// Số mạng đã cấu hình (ô khác rỗng).
inline int countNetworks(const char* const* configured, int n) {
  int c = 0;
  for (int i = 0; i < n; i++) c += configured[i] && configured[i][0];
  return c;
}
