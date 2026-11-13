# Backend – VPS

FastAPI + SQLModel + PostgreSQL 16, Caddy làm reverse proxy và tự cấp HTTPS (Let's Encrypt), chạy bằng Docker Compose (`caddy`, `api`, `db`). Thiết kế ở kế hoạch, giai đoạn 6.

- API: [`../docs/api.md`](../docs/api.md). Bảng: [`../docs/data-schema.md`](../docs/data-schema.md).
- Chạy thử trên laptop bằng Docker trước khi thuê VPS.
- Trên VPS: SSH bằng khóa, tắt đăng nhập root và mật khẩu, `ufw` chỉ mở 22/80/443, `fail2ban`, `unattended-upgrades`, `pg_dump` hằng ngày giữ 7 bản.

```bash
cp .env.example .env   # rồi điền
```
