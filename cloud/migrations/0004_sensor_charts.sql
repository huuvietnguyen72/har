-- Biểu đồ cảm biến trên dashboard (trang Cảm biến).
-- Trực tiếp: 2 phút gần nhất, điểm 5 Hz do Pi gom (gửi kèm trạng thái 5 s); 1 dòng mỗi thiết bị, ghi đè.
--   imu  = JSON [[t, svm trung bình (g), svm lớn nhất (g), con quay trung bình (°/s)], ...]
--   baro = JSON [[t, áp suất (Pa)], ...]
CREATE TABLE sensor_live (
    dev TEXT PRIMARY KEY,
    t INTEGER NOT NULL,      -- thời điểm điểm mới nhất
    imu TEXT NOT NULL DEFAULT '[]',
    baro TEXT NOT NULL DEFAULT '[]'
);
-- Lịch sử 24 giờ: số liệu 1 phút gần nhất, ghi cùng dòng status_log (≤ 1 dòng/phút)
ALTER TABLE status_log ADD COLUMN svm_mean REAL;   -- g
ALTER TABLE status_log ADD COLUMN svm_max REAL;    -- g
ALTER TABLE status_log ADD COLUMN gyro_mean REAL;  -- °/s
ALTER TABLE status_log ADD COLUMN p_hpa REAL;      -- hPa
