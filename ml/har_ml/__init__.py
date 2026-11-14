"""Xử lý dataset và huấn luyện model HAR. Đặc trưng lấy từ har_edge.features (dùng chung với Pi)."""
import sys

# Console Windows mặc định cp1252 không in được tiếng Việt
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure") and (_s.encoding or "").lower() not in ("utf-8", "utf8"):
        _s.reconfigure(encoding="utf-8", errors="replace")
