# Web app

React + Vite + TypeScript, React Router, Recharts. Phục vụ từ VPS qua Caddy. Thiết kế ở kế hoạch, giai đoạn 6.

| Trang | Nội dung chính |
| --- | --- |
| Tổng quan | Hoạt động hiện tại + độ tin cậy, online, pin, nhiệt độ, độ ẩm; dải hoạt động 1 giờ qua; cảnh báo gần nhất |
| Lịch sử | Dòng thời gian hoạt động theo ngày, thời lượng mỗi hoạt động, so sánh 7 ngày |
| Cảnh báo | Bảng sự kiện té/SOS/kỹ thuật, nút "Đã xử lý", thông báo tức thời qua WebSocket |
| Đánh giá model | Bảng thí nghiệm A1–D, ma trận nhầm lẫn, F1 từng lớp, độ trễ, thời lượng pin |

Các trang chỉ gọi module `dataSource` (`apiDataSource` gọi VPS, `mockDataSource` đọc JSON mẫu), nên làm được giao diện trước khi backend xong.
