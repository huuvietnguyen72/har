# Dựng VPS từ đầu

Làm theo đúng thứ tự; cũng là hướng dẫn dựng lại khi VPS hỏng (chỉ cần thêm bước khôi phục DB).

## 1. Thuê VPS và tên miền

- Ubuntu 24.04 LTS, 1 vCPU, 1–2 GB RAM, ≥ 20 GB SSD, đặt ở Việt Nam hoặc Singapore.
- Tên miền: tạo subdomain trên <https://www.duckdns.org>, trỏ về IP của VPS (bản ghi A).
  Kiểm tra: `nslookup ten-mien.duckdns.org` ra đúng IP.

## 2. Bảo mật máy chủ

```bash
# Trên laptop
ssh root@IP
adduser har && usermod -aG sudo har
exit
ssh-copy-id har@IP            # rồi thử: ssh har@IP (không hỏi mật khẩu)

# Trên VPS, user har
git clone https://github.com/huuvietnguyen72/har.git && cd har
sudo bash backend/scripts/harden-vps.sh har
exit && ssh har@IP            # đăng nhập lại để có quyền docker
```

Script bật `ufw` (22/80/443), `fail2ban`, `unattended-upgrades`, tắt SSH mật khẩu và root, cài Docker.

## 3. Chạy hệ thống

```bash
cd ~/har/backend
cp .env.example .env
nano .env                     # DOMAIN, POSTGRES_PASSWORD, JWT_SECRET (openssl rand -hex 32)
docker compose up -d --build
docker compose ps             # 3 container: caddy, api, db
curl https://$DOMAIN/api/health
```

Caddy tự xin chứng chỉ HTTPS lần đầu (cần cổng 80/443 mở và DNS đã trỏ đúng).

## 4. Tạo tài khoản và API key thiết bị

```bash
docker compose exec api python -m app.cli create-user --email ban@nhom.vn --role admin
docker compose exec api python -m app.cli create-user --email giangvien@truong.edu.vn --role viewer
docker compose exec api python -m app.cli create-device --dev har01 --alias "Người đeo 1"
```

API key in ra chỉ hiện một lần → ghi vào `VPS_DEVICE_KEY` trong `edge/.env` trên Pi (và trên laptop huấn luyện để đẩy `metrics.json`).

## 5. Sao lưu và giám sát

```bash
crontab -e
# 0 3 * * * /home/har/har/backend/scripts/backup.sh >> /home/har/backup.log 2>&1
```

- Mỗi tuần chép một bản về máy nhóm: `scp har@IP:~/har-backups/<file mới nhất> .`
- Thử khôi phục ít nhất một lần: `scripts/restore.sh ~/har-backups/<file>.sql.gz`
- UptimeRobot: monitor HTTP(s) `https://<tên miền>/api/health`, chu kỳ 5 phút, báo qua email/Telegram.

## 6. Cập nhật code

```bash
cd ~/har && git pull && cd backend && docker compose up -d --build
```

Migration (Alembic) tự chạy khi container `api` khởi động. Đổi model trong `api/app/models.py` thì tạo migration mới trên laptop:

```bash
cd backend/api
DATABASE_URL=sqlite:///tmp.db alembic upgrade head
DATABASE_URL=sqlite:///tmp.db alembic revision --autogenerate -m "mo ta thay doi"
```

## Kiểm tra tiêu chí giai đoạn 6

- [ ] Mở `https://<tên miền>` bằng 4G điện thoại
- [ ] `curl -i https://<tên miền>/api/status` → `401`
- [ ] `sudo reboot` → sau 1 phút `docker compose ps` đủ 3 container, dữ liệu còn
- [ ] Khôi phục DB từ bản sao lưu thành công
