# Backend – VPS

FastAPI + SQLModel + PostgreSQL 16, Caddy làm reverse proxy, tự cấp HTTPS và phục vụ web app; chạy bằng Docker Compose (`caddy`, `api`, `db`). Thiết kế ở kế hoạch, giai đoạn 6.

- API: [`../docs/api.md`](../docs/api.md) — tài liệu tự sinh ở `https://<tên miền>/api/docs`.
- Bảng: [`../docs/data-schema.md`](../docs/data-schema.md), migration trong `api/alembic/`.
- Dựng VPS từ đầu, sao lưu, giám sát: [`DEPLOY.md`](DEPLOY.md).

```
backend/
├── docker-compose.yml     caddy + api + db
├── Caddyfile              HTTPS, /api và /ws → api, còn lại → web app
├── caddy.Dockerfile       build webapp/ rồi đóng gói cùng Caddy
├── api/
│   ├── app/main.py        FastAPI, /api/health, /ws
│   ├── app/routers/       auth, ingest (Pi, X-Device-Key), read (web app, JWT)
│   ├── app/models.py      bảng SQLModel
│   ├── app/cli.py         tạo tài khoản, cấp API key thiết bị
│   ├── alembic/           migration
│   └── tests/             pytest (SQLite, không cần Docker)
└── scripts/               backup.sh, restore.sh, harden-vps.sh
```

## Chạy test (không cần Docker)

```bash
cd backend/api
python -m venv .venv && .venv/Scripts/activate      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## Chạy API trên laptop không cần Docker

```bash
cd backend/api
set DATABASE_URL=sqlite:///dev.db          # PowerShell: $env:DATABASE_URL="sqlite:///dev.db"
alembic upgrade head
python -m app.cli create-user --email a@b.c --password matkhau123 --role admin
python -m app.cli create-device --dev har01
set CORS_ORIGINS=http://localhost:5173
uvicorn app.main:app --reload
```

Rồi chạy web app với `VITE_DATA_SOURCE=api` và `VITE_API_URL=http://localhost:8000/api`.

## Chạy cả hệ thống bằng Docker trên laptop

```bash
cd backend
cp .env.example .env      # DOMAIN=localhost
docker compose up -d --build
```

Mở `https://localhost` (chứng chỉ tự ký, trình duyệt sẽ cảnh báo).
