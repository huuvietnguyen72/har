-- Nhịp tim của Pi (har-uplink gửi mỗi 60 s, độc lập với bộ đeo) và trạng thái cảnh báo "Pi mất kết nối"
-- do Cron Trigger của Worker kiểm tra (xem scheduled() trong src/index.ts).
ALTER TABLE devices ADD COLUMN pi_seen_at INTEGER;        -- lần cuối Pi gọi cloud (epoch ms, giờ cloud)
ALTER TABLE devices ADD COLUMN pi_offline_since INTEGER;  -- khác NULL: đã báo mất kết nối, chờ Pi gửi lại
