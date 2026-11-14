# Build web app React rồi đóng gói cùng Caddy. Context là thư mục gốc repo.
FROM node:22-alpine AS web
WORKDIR /web
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
ENV VITE_DATA_SOURCE=api VITE_API_URL=/api
RUN npm run build

FROM caddy:2-alpine
COPY --from=web /web/dist /srv
