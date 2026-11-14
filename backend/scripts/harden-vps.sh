#!/usr/bin/env bash
# Cấu hình bảo mật cơ bản cho VPS Ubuntu 24.04. Chạy bằng root MỘT lần, SAU KHI đã
# copy khóa SSH vào user thường (ssh-copy-id har@IP) và thử đăng nhập bằng khóa thành công.
#   sudo bash scripts/harden-vps.sh har
set -euo pipefail
USER_NAME="${1:?Truyền tên user thường, ví dụ: har}"

apt-get update && apt-get -y upgrade
apt-get -y install ufw fail2ban unattended-upgrades ca-certificates curl

# SSH: chỉ khóa, không mật khẩu, không root
install -d /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/99-har.conf <<CONF
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
systemctl reload ssh

# Tường lửa: chỉ 22/80/443
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

# Docker (repo chính thức)
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$USER_NAME"
echo "Xong. Đăng xuất rồi đăng nhập lại bằng $USER_NAME để dùng docker."
