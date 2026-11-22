"""har-notify: đọc bảng alerts trong SQLite và gửi Telegram.

- Cùng một sự kiện chỉ gửi một lần (cột notified)
- Cảnh báo cùng loại của cùng thiết bị cách nhau < 20 s thì gộp (cùng một sự cố bị báo nhiều lần), không gửi lại;
  hai cú té cách nhau xa hơn vẫn có tin riêng (thử 21/11: cú té thứ hai sau 46 s từng bị gộp mất)
- Mất Internet: giữ trong hàng, gửi khi có mạng, ghi rõ "gửi trễ" và giờ thật
- Cảnh báo đã hủy (cancelled) chỉ ghi lại, không gửi
- Nhiều người nhận (TELEGRAM_CHAT_ID="a,b,c"): gửi lần lượt, ghi từng người đã nhận (bảng alert_deliveries), nên
  lỗi mạng giữa chừng thì lần sau chỉ gửi cho người còn thiếu. Người nhận lỗi vĩnh viễn (chặn bot, chưa bấm Start,
  sai chat ID) bị bỏ qua và ghi log, không làm kẹt cảnh báo của người khác

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
from .bot import fall_buttons
from .config import Config, chat_ids, load_config
from .logutil import setup_logging

log = logging.getLogger("har-notify")

MERGE_MS = 20_000
LATE_MS = 60_000
VI = {"stand": "Đứng", "sit": "Ngồi", "lie": "Nằm", "walk": "Đi", "stairs_up": "Lên cầu thang",
      "stairs_down": "Xuống cầu thang", "fall": "Té"}
TITLE = {"fall": "🚨 PHÁT HIỆN TÉ NGÃ", "sos": "🆘 GỌI TRỢ GIÚP (SOS)", "low_battery": "🔋 Pin yếu",
         "offline": "📴 Thiết bị mất kết nối", "wearer_ack": "✋ Người đeo đã bấm nút"}
SEVERITY = {"high": "cao", "medium": "trung bình", "info": "thông tin"}
SOURCE = {"both": "ngưỡng + model", "threshold": "ngưỡng trên thiết bị", "model": "model trên Pi",
          "device": "nút trên thiết bị", "edge": "Pi"}


def _hms(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000).strftime("%H:%M:%S %d/%m/%Y")


def format_message(a: dict, now: int, webapp_url: str = "") -> str:
    lines = [f"<b>{TITLE.get(a['type'], a['type'])}</b>", f"Thiết bị: <code>{escape(a['dev'])}</code>",
             f"Thời điểm: {_hms(a['t'])}"]
    if a["type"] == "wearer_ack":
        if a.get("ref_t"):
            lines.append(f"Sau cảnh báo té lúc {_hms(a['ref_t'])}, người đeo đã bấm nút trên bộ đeo và tắt còi.")
        lines.append("Người đeo còn phản hồi, nhưng <b>vẫn cần gọi hoặc đến kiểm tra</b> rồi bấm Đã xử lý.")
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


def _describe(e: httpx.HTTPStatusError) -> str:
    try:
        return f"{e.response.status_code} {e.response.json().get('description', '')}".strip()
    except ValueError:
        return str(e.response.status_code)


def _permanent(e: httpx.HTTPStatusError) -> bool:
    """Lỗi do người nhận, gửi lại cũng vô ích: 403 (chặn bot, chưa bấm Start, tài khoản bị xóa), 400 sai chat ID."""
    code = e.response.status_code
    return code == 403 or (code == 400 and "chat not found" in _describe(e).lower())


class Notifier:
    def __init__(self, cfg: Config, conn, client: httpx.Client | None = None):
        self.cfg = cfg
        self.conn = conn
        self.client = client or httpx.Client(timeout=10)
        self.chats = chat_ids(cfg.telegram_chat_id)
        self.enabled = bool(cfg.telegram_bot_token and self.chats)
        if not self.enabled:
            log.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — chỉ in ra màn hình")

    def send(self, text: str, reply_markup: dict | None = None, chat_id: str | None = None) -> None:
        if not self.enabled:
            print(text, flush=True)
            return
        body = {"chat_id": chat_id or self.chats[0], "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True}
        if reply_markup:
            body["reply_markup"] = reply_markup
        r = self.client.post(f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage", json=body)
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
                log.info("Gộp cảnh báo %s vào cảnh báo trước (< %d s)", r["id"], MERGE_MS // 1000)
                self._mark(r["id"], now, 3)
                continue
            # nút "Tắt còi" / "Đã kiểm tra, ổn" do har-bot xử lý
            buttons = fall_buttons(r["id"]) if a.get("type") in ("fall", "sos") else None
            text = format_message(a, now, self.cfg.webapp_url)
            if not self.enabled:
                self.send(text, buttons)
            else:
                done = {d["chat_id"] for d in self.conn.execute(
                    "SELECT chat_id FROM alert_deliveries WHERE alert_id = ?", (r["id"],))}
                for chat in self.chats:
                    if chat in done:
                        continue
                    try:
                        self.send(text, buttons, chat)
                    except httpx.HTTPStatusError as e:
                        if _permanent(e):
                            log.warning("Bỏ người nhận %s: Telegram từ chối (%s)", chat, _describe(e))
                            self._deliver(r["id"], chat, now, 2, _describe(e))
                            continue
                        self._retry_later(r["id"], e)
                    except httpx.HTTPError as e:
                        self._retry_later(r["id"], e)
                    self._deliver(r["id"], chat, now, 1)
            self._mark(r["id"], now, 1)
            sent += 1
            log.info("Đã báo %s (%s)", r["id"], f"Telegram, {len(self.chats)} người nhận" if self.enabled else "màn hình")
        return sent

    def _retry_later(self, aid: str, e: Exception):
        self.conn.execute("UPDATE alerts SET attempts = attempts + 1 WHERE id = ?", (aid,))
        log.warning("Gửi Telegram lỗi (%s), sẽ thử lại", e)
        raise e  # giữ thứ tự; vòng ngoài chờ lâu dần rồi thử lại, chỉ gửi cho người còn thiếu

    def _deliver(self, aid: str, chat: str, now: int, state: int, detail: str | None = None) -> None:
        self.conn.execute("INSERT OR REPLACE INTO alert_deliveries (alert_id, chat_id, state, at, detail) VALUES (?, ?, ?, ?, ?)",
                          (aid, chat, state, now, detail))

    def _mark(self, aid: str, now: int, state: int) -> None:
        # 1 = đã gửi, 2 = không cần gửi (đã hủy), 3 = gộp với cảnh báo trước
        self.conn.execute("UPDATE alerts SET notified = ?, notified_at = ? WHERE id = ?", (state, now, aid))


def main() -> None:
    setup_logging()  # che token Telegram, tắt log từng request của httpx
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
