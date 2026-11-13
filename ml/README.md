# ML – dataset và huấn luyện

Huấn luyện trên laptop hoặc Google Colab, chỉ suy luận trên Pi. Thiết kế ở kế hoạch, giai đoạn 4.

- Dataset thô để ở Google Drive của nhóm, không commit. Đặt bản sao cục bộ vào `data/raw/` (đã nằm trong `.gitignore`).
- Cửa sổ 2,5 s (125 mẫu), chồng lấn 50 %; thử thêm 2,0 s.
- Chia tập theo người (GroupKFold / leave-one-subject-out), không chia ngẫu nhiên theo cửa sổ.
- Model 1: Random Forest trên đặc trưng thống kê. Model 2: 1D-CNN (Keras) → TFLite (có bản int8).

| Thí nghiệm | Biến thay đổi |
| --- | --- |
| A1 / A2 | RF: chỉ IMU / IMU + BMP280 |
| B1 / B2 | 1D-CNN: chỉ IMU / IMU + BMP280 |
| C | Cửa sổ 2,0 s vs 2,5 s |
| D | Ngưỡng trên ESP32 vs model vs kết hợp |

Mỗi thí nghiệm xuất `results/<thí nghiệm>/metrics.json` theo bảng `metrics` trong [`../docs/data-schema.md`](../docs/data-schema.md), rồi đẩy lên VPS để trang Đánh giá model hiển thị.
