-- Người đeo bấm nút trên bộ đeo SAU khi té đã xác nhận (tắt còi): thời điểm bấm, epoch ms (giờ bộ đeo).
-- Không thay cho "đã xử lý": người thân vẫn phải kiểm tra rồi bấm Đã xử lý.
ALTER TABLE events ADD COLUMN wearer_ack_at INTEGER;
