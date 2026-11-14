#!/usr/bin/env bash
# Cài đặt Pi 4 (Raspberry Pi OS 64-bit Bookworm) cho HAR. Chạy từ thư mục edge/:
#   sudo bash deploy/setup-pi.sh
# Biến tùy chọn: HOTSPOT_SSID (mặc định har-hotspot), HOTSPOT_PASS (bắt buộc ≥ 8 ký tự)
set -euo pipefail
EDGE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSID="${HOTSPOT_SSID:-har-hotspot}"
PASS="${HOTSPOT_PASS:?Đặt HOTSPOT_PASS=matkhau (>= 8 ký tự)}"
RUN_USER="${SUDO_USER:-pi}"

apt-get update
apt-get -y install mosquitto mosquitto-clients chrony python3-venv python3-dev avahi-daemon ufw

# 1. Tên mạng hargw.local (mDNS) để ESP32 tìm Pi khi dùng phương án dự phòng
hostnamectl set-hostname hargw
systemctl enable --now avahi-daemon

# 2. Hotspot trên wlan0 (Internet đi qua Ethernet hoặc USB tethering)
if ! nmcli -t -f NAME connection show | grep -qx har-hotspot; then
  nmcli connection add type wifi ifname wlan0 con-name har-hotspot autoconnect yes ssid "$SSID" \
    802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS"
fi
nmcli connection up har-hotspot || true

# 3. Mosquitto
install -m 644 "$EDGE_DIR/deploy/mosquitto-har.conf" /etc/mosquitto/conf.d/har.conf
if [ ! -f /etc/mosquitto/passwd ]; then
  echo "Tạo tài khoản MQTT cho ESP32 (har01) và cho các dịch vụ Pi (har-edge):"
  mosquitto_passwd -c /etc/mosquitto/passwd har01
  mosquitto_passwd /etc/mosquitto/passwd har-edge
fi
chown mosquitto: /etc/mosquitto/passwd && chmod 600 /etc/mosquitto/passwd
systemctl enable --now mosquitto && systemctl restart mosquitto

# 4. chrony làm máy chủ giờ
install -d /etc/chrony/conf.d
install -m 644 "$EDGE_DIR/deploy/chrony-har.conf" /etc/chrony/conf.d/har.conf
grep -q "confdir /etc/chrony/conf.d" /etc/chrony/chrony.conf || echo "confdir /etc/chrony/conf.d" >> /etc/chrony/chrony.conf
systemctl enable --now chrony && systemctl restart chrony

# 5. Tường lửa: MQTT (1883) và NTP (123) chỉ từ mạng hotspot
ufw allow ssh
ufw allow from 10.42.0.0/24 to any port 1883 proto tcp
ufw allow from 10.42.0.0/24 to any port 123 proto udp
ufw allow in on wlan0 to any port 67 proto udp   # DHCP cho hotspot
ufw allow in on wlan0 to any port 53             # DNS cho hotspot
ufw --force enable

# 6. Python venv + dịch vụ
sudo -u "$RUN_USER" python3 -m venv "$EDGE_DIR/.venv"
sudo -u "$RUN_USER" "$EDGE_DIR/.venv/bin/pip" install -q -e "$EDGE_DIR"
[ -f "$EDGE_DIR/.env" ] || sudo -u "$RUN_USER" cp "$EDGE_DIR/.env.example" "$EDGE_DIR/.env"
for s in ingest infer uplink notify; do
  sed "s#/home/pi/har/edge#$EDGE_DIR#g; s#User=pi#User=$RUN_USER#" "$EDGE_DIR/deploy/har-$s.service" > /etc/systemd/system/har-$s.service
done
systemctl daemon-reload
systemctl enable har-ingest har-infer har-uplink har-notify
echo
echo "Xong. Sửa $EDGE_DIR/.env (MQTT_PASSWORD của har-edge, VPS_*, TELEGRAM_*), rồi:"
echo "  sudo systemctl restart har-ingest har-infer har-uplink har-notify"
echo "  journalctl -fu har-infer"
