# Web app

React 18 + Vite + TypeScript, React Router, Recharts. Build xong được Caddy phục vụ từ VPS (xem `backend/caddy.Dockerfile`). Thiết kế ở kế hoạch, giai đoạn 6.

| Trang | Nội dung chính |
| --- | --- |
| Đăng nhập | Tài khoản do nhóm cấp (JWT 12 giờ), không tự đăng ký |
| Tổng quan | Hoạt động hiện tại + độ tin cậy, online, pin, nhiệt độ, độ ẩm, Wi-Fi; dải hoạt động 1 giờ qua; cảnh báo gần nhất; băng rôn đỏ khi có cảnh báo chưa xử lý |
| Lịch sử | Chọn ngày; dòng thời gian 24 giờ có mốc té; thời lượng mỗi hoạt động; so sánh 7 ngày |
| Cảnh báo | Bảng té/SOS/pin yếu/mất kết nối, nút "Đã xử lý", thông báo tức thời qua WebSocket |
| Đánh giá model | Model đang chạy; bảng A1–C; F1 từng lớp có/không BMP280; ma trận nhầm lẫn; thí nghiệm D; độ trễ từng chặng; đồ thị pin |

Các trang chỉ gọi module `dataSource` (`src/data/`):

- `apiDataSource` — fetch + WebSocket tới VPS; WebSocket rớt thì tự hỏi lại mỗi 10 s và kết nối lại.
- `mockDataSource` — dữ liệu mẫu sinh trong trình duyệt (có một cảnh báo té mẫu sau 40 s), để làm giao diện khi chưa có backend.

## Chạy

```bash
cd webapp
npm install
cp .env.example .env.local      # VITE_DATA_SOURCE=mock hoặc api
npm run dev                     # http://localhost:5173
npm run build                   # kiểm tra kiểu + build vào dist/
```

Gọi backend chạy trên laptop: `VITE_DATA_SOURCE=api`, `VITE_API_URL=http://localhost:8000/api`, và đặt `CORS_ORIGINS=http://localhost:5173` cho backend. Trên VPS không cần gì thêm: `caddy.Dockerfile` build với `VITE_API_URL=/api`.

Giao diện tự theo chế độ sáng/tối của hệ thống và dùng được trên điện thoại (bảng chuyển thành dạng thẻ).
