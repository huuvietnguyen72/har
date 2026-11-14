"""har-notify: đọc bảng alerts trong SQLite và gửi Telegram.

- Cùng một sự kiện chỉ gửi một lần (cột notified)
- Cảnh báo cùng loại của cùng thiết bị cách nhau < 60 s thì gộp, không gửi lại
- Mất Internet: giữ trong hàng, gửi khi có mạng, ghi rõ "gửi trễ" và giờ thật
- Cảnh báo đã hủy (cancelled) chỉ ghi lại, không gửi

Chạy: python -m har_edge.notify
"""
import json
import logging
import signal
import threading
from datetime import datetime
from html import escape

import httpx

from . import store
from .config import Config, load_config

log = logging.getLogger("har-notify")

MERGE_MS = 60_000
LATE_MS = 60_000
VI = {"stand": "Đứng", "sit": "Ngồi", "lie": "Nằm", "walk": "Đi", "run": "Chạy", "stairs_up": "Lên cầu thang",
      "stairs_down": "Xuống cầu thang", "fall": "Té"}
TITLE = {"fall": "🚨 PHÁT HIỆN TÉ NGÃ", "sos": "🆘 GỌI TRỢ GIÚP (SOS)", "low_battery": "🔋 Pin yếu",
         "offline": "📴 Thiết bị mất kết nối"}
SEVERITY = {"high": "cao", "medium": "trung bình", "info": "thông tin"}
SOURCE = {"both": "ngưỡng + model", "threshold": "ngưỡng trên thiết bị", "model": "model trên Pi",
          "device": "nút trên thiết bị", "edge": "Pi"}


def _hms(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000).strftime("%H:%M:%S %d/%m/%Y")


def format_message(a: dict, now: int, webapp_url: str = "") -> str:
    lines = [f"<b>{TITLE.get(a['type'], a['type'])}</b>", f"Thiết bị: <code>{escape(a['dev'])}</code>",
             f"Thời điểm: {_hms(a['t'])}"]
    if a["type"] == "fall":
        lines.append(f"Mức: {SEVERITY.get(a.get('severity'), a.get('severity'))} · Nguồn: {SOURCE.get(a.get('source'), a.get('source'))}")
        if a.get("prob") is not None:
            lines.append(f"Xác suất té (model): {a['prob']:.0%}")
        if a.get("prev_label"):
            lines.append(f"Hoạt động trước đó: {VI.get(a['prev_label'], a['prev_label'])}")
    if a["type"] == "low_battery" and a.get("battery_v"):
        lines.append(f"Điện áp pin: {a['battery_v']:.2f} V")
    if a.get("battery_pct") is not None:
        lines.append(f"Pin: {a['battery_pct']:.0f}%")
    if now - a["t"] > LATE_MS:
        lines.append(f"⚠️ <i>Gửi trễ</i> — giờ xảy ra thật: {_hms(a['t'])}")
    if webapp_url:
        lines.append(f'<a href="{escape(webapp_url)}/alerts">Mở trang Cảnh báo</a>')
    return "\n".join(lines)


class Notifier:
    def __init__(self, cfg: Config, conn, client: httpx.Client | None = None):
        self.cfg = cfg
        self.conn = conn
        self.client = client or httpx.Client(timeout=10)
        self.enabled = bool(cfg.telegram_bot_token and cfg.telegram_chat_id)
        if not self.enabled:
            log.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — chỉ in ra màn hình")

    def send(self, text: str) -> None:
        if not self.enabled:
            print(text, flush=True)
            return
        r = self.client.post(
            f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage",
            json={"chat_id": self.cfg.telegram_chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
        )
        r.raise_for_status()

    def step(self, now: int | None = None) -> int:
        now = now or store.now_ms()
        rows = self.conn.execute(
            "SELECT * FROM alerts WHERE notified = 0 ORDER BY t LIMIT 20").fetchall()
        sent = 0
        for r in rows:
            a = json.loads(r["payload"])
            if not r["notify"] or a.get("cancelled"):
                self._mark(r["id"], now, 2)  # không cần gửi
                continue
            dup = self.conn.execute(
                "SELECT 1 FROM alerts WHERE dev = ? AND type = ? AND notified = 1 AND id != ? AND ABS(t - ?) < ?",
                (r["dev"], r["type"], r["id"], r["t"], MERGE_MS)).fetchone()
            if dup:
                log.info("Gộp cảnh báo %s vào cảnh báo trước (< 60 s)", r["id"])
                self._mark(r["id"], now, 3)
                continue
            try:
                self.send(format_message(a, now, self.cfg.webapp_url))
            except httpx.HTTPError as e:
                self.conn.execute("UPDATE alerts SET attempts = attempts + 1 WHERE id = ?", (r["id"],))
                log.warning("Gửi Telegram lỗi (%s), sẽ thử lại", e)
                raise  # giữ thứ tự; vòng ngoài chờ lâu dần rồi thử lại
            self._mark(r["id"], now, 1)
            sent += 1
            log.info("Đã gửi Telegram cho %s", r["id"])
        return sent

    def _mark(self, aid: str, now: int, state: int) -> None:
        # 1 = đã gửi, 2 = không cần gửi (đã hủy), 3 = gộp với cảnh báo trước
        self.conn.execute("UPDATE alerts SET notified = ?, notified_at = ? WHERE id = ?", (state, now, aid))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config()
    n = Notifier(cfg, store.connect(cfg.db_path))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    fails = 0
    while not stop.is_set():
        try:
            n.step()
            fails = 0
            stop.wait(1.0)
        except Exception:
            fails += 1
            log.exception("Lỗi vòng notify")
            stop.wait(min(60, 2**fails))


if __name__ == "__main__":
    main()
