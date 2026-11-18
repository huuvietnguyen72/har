"""har-bot: nhận lệnh từ Telegram (chạy song song har-notify, dùng chung bot).

Lệnh (chỉ nhận từ chat trong TELEGRAM_CHAT_ID / TELEGRAM_ALLOWED_IDS):
- /trangthai : đang làm gì, từ lúc nào, bộ đeo online không, cảnh báo gần nhất
- /homnay    : thời gian từng hoạt động hôm nay (theo dự đoán), số cảnh báo
- /coi       : chọn bật còi 5 / 30 / 60 giây (hoặc /coi 20, tối đa 60 s) để tìm bộ đeo hoặc gọi người đeo;
               tin trả lời có nút "Dừng còi" (nút trên bộ đeo không tắt được còi này)
- /tatcoi    : dừng còi /coi, hoặc tắt còi cảnh báo sau khi té đã xác nhận
- /hieuchinh : hiệu chỉnh hướng đứng thẳng (người đeo đứng thẳng yên ~4 s); người đeo cũng tự làm được
               bằng cách nhấn nút 3 lần. Kết quả mọi lần hiệu chỉnh (Telegram hoặc nút) được báo kèm góc lệch
               so với hướng cũ và nút "Khôi phục hướng cũ".
Nút dưới tin cảnh báo té (har-notify gắn): "Tắt còi" và "Đã kiểm tra, ổn".

An toàn: firmware xử lý cancel_alarm trong 10 s chờ hủy như người đeo tự hủy (cú ngã không được báo nữa),
nên bot TỪ CHỐI tắt còi khi bộ đeo đang nghi té mà chưa xác nhận; chỉ người đeo được tự hủy bằng nút.

Long polling (getUpdates) nên không cần mở cổng hay địa chỉ công khai. Tin cũ hơn 2 phút (bot vừa khởi động
lại) bị bỏ qua để không bật còi muộn.

Chạy: python -m har_edge.bot
"""
import json
import logging
import math
import re
import signal
import threading
from datetime import datetime
from html import escape

import httpx

from . import store
from .config import Config, load_config
from .logutil import setup_logging
from .mqtt import make_client, publish_json, topic_parts

log = logging.getLogger("har-bot")

VI = {"stand": "Đứng", "sit": "Ngồi", "lie": "Nằm", "walk": "Đi bộ", "stairs_up": "Lên cầu thang",
      "stairs_down": "Xuống cầu thang", "fall": "Té"}
ORDER = ["stand", "sit", "lie", "walk", "stairs_up", "stairs_down", "fall"]
COMMANDS = [("trangthai", "Người đeo đang làm gì"), ("homnay", "Thống kê hôm nay"),
            ("coi", "Bật còi 5 / 30 / 60 giây"), ("tatcoi", "Dừng còi đang kêu"),
            ("hieuchinh", "Hiệu chỉnh hướng đứng thẳng (đổi người/cách đeo)"),
            ("help", "Danh sách lệnh")]
CANCEL_WINDOW_MS = 10_000  # firmware/include/config.h
CONFIRMED_BUZZ_MS = 30_000
PENDING_MS = 15_000  # nghi té chưa có kết quả quá mốc này coi như đã xong (har-infer cũng dùng 15 s)
STALE_MSG_S = 120
GAP_MS = 5_000  # khoảng trống giữa hai dự đoán lớn hơn mốc này = không có dữ liệu
ONLINE_MS = 15_000
BEEP_OPTIONS_S = (5, 30, 60)
MAX_BEEP_S = 60
STOP_BEEP = {"inline_keyboard": [[{"text": "⏹ Dừng còi", "callback_data": "beepstop"}]]}
UPRIGHT_DEFAULT = (-1.0, 0.0, 0.0)  # cách đeo chuẩn: trục X chỉ xuống đất (firmware/include/config.h)
UPRIGHT_WARN_DEG = 45  # đổi nhiều hơn mức này: nhắc kiểm tra (giống record.py)
CAL_TIMEOUT_MS = 25_000
CAL_FAIL = {"moving": "người đeo đang cử động", "bad_gravity": "gia tốc đo được không phải 1 g"}


def fall_buttons(alert_id: str) -> dict:
    """Nút dưới tin cảnh báo té/SOS (har-notify gắn, har-bot xử lý)."""
    return {"inline_keyboard": [[{"text": "🔕 Tắt còi", "callback_data": f"silence:{alert_id}"},
                                 {"text": "✅ Đã kiểm tra, ổn", "callback_data": f"ack:{alert_id}"}]]}


def beep_menu() -> dict:
    return {"inline_keyboard": [[{"text": f"🔔 {s} giây", "callback_data": f"beep:{s}"} for s in BEEP_OPTIONS_S]]}


def angle_deg(a, b) -> float | None:
    """Góc (độ) giữa hai vector 3 chiều; None nếu thiếu."""
    try:
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        c = sum(x * y for x, y in zip(a, b)) / (na * nb)
    except (TypeError, ZeroDivisionError):
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _hm(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000).strftime("%H:%M")


def _hms(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000).strftime("%H:%M:%S")


def _dur(ms: float) -> str:
    s = int(round(ms / 1000))
    h, m = divmod(s // 60, 60)
    if h:
        return f"{h} giờ {m} phút"
    if m:
        return f"{m} phút"
    return f"{s} giây"


def _start_of_day(now_ms: int) -> int:
    d = datetime.fromtimestamp(now_ms / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


def _who(user: dict | None) -> str:
    if not user:
        return "Ai đó"
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return name or user.get("username") or str(user.get("id"))


class Bot:
    def __init__(self, cfg: Config, conn, publish, client: httpx.Client | None = None, now=store.now_ms):
        self.cfg = cfg
        self.conn = conn
        self.publish = publish  # publish(topic, dict)
        self.client = client or httpx.Client(timeout=60)
        self.now = now
        ids = [cfg.telegram_chat_id, *cfg.telegram_allowed_ids.split(",")]
        self.allowed = {i.strip() for i in ids if i.strip()}
        self.status: dict[str, dict] = {}  # dev -> status mới nhất (retained từ ESP32)
        self.beep_until: dict[str, int] = {}  # dev -> lúc còi /coi tự dừng
        self.cal_pending: dict[str, dict] = {}  # id lệnh /hieuchinh -> {chat, who, dev, t}
        self.cal_done: dict[str, tuple] = {}  # dev -> (upright_req, upright_result) đã báo
        self.restore: dict[str, tuple] = {}  # id lần hiệu chỉnh -> (dev, hướng cũ)
        self.lock = threading.Lock()  # on_status chạy trên luồng MQTT
        self.offset = 0

    # ---------- Telegram ----------
    def api(self, method: str, **params) -> dict:
        r = self.client.post(f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/{method}", json=params,
                             timeout=params.get("timeout", 0) + 15)
        r.raise_for_status()
        return r.json()

    def reply(self, chat_id, text: str, **kw) -> None:
        self.api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True, **kw)

    def register_commands(self) -> None:
        self.api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])

    def poll_once(self, timeout: int = 30) -> int:
        res = self.api("getUpdates", offset=self.offset, timeout=timeout,
                       allowed_updates=["message", "callback_query"]).get("result", [])
        for u in res:
            self.offset = max(self.offset, u["update_id"] + 1)
            try:
                self.handle_update(u)
            except Exception:
                log.exception("Lỗi xử lý update %s", u.get("update_id"))
        return len(res)

    # ---------- xử lý ----------
    def handle_update(self, u: dict) -> None:
        if "callback_query" in u:
            return self.handle_callback(u["callback_query"])
        msg = u.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        if chat not in self.allowed:
            log.warning("Bỏ lệnh từ chat không được phép %s: %s", chat, text[:40])
            return
        if self.now() / 1000 - msg.get("date", 0) > STALE_MSG_S:
            log.info("Bỏ lệnh cũ (bot vừa khởi động lại): %s", text[:40])
            return
        cmd, *args = text.split()
        cmd = cmd[1:].split("@")[0].lower()
        who = _who(msg.get("from"))
        if cmd == "trangthai":
            self.reply(chat, self.status_text())
        elif cmd == "homnay":
            self.reply(chat, self.today_text())
        elif cmd == "coi":
            if not args:
                self.reply(chat, "Bật còi trên bộ đeo trong bao lâu?", reply_markup=beep_menu())
            else:
                text, ok = self.beep(args[0], who)
                self.reply(chat, text, **({"reply_markup": STOP_BEEP} if ok else {}))
        elif cmd == "tatcoi":
            self.reply(chat, self.silence(who))
        elif cmd == "hieuchinh":
            self.reply(chat, self.calibrate(chat, who))
        elif cmd in ("start", "help"):
            self.reply(chat, "<b>Bộ đeo HAR</b>\n" + "\n".join(f"/{c} – {d}" for c, d in COMMANDS))
        else:
            self.reply(chat, "Không hiểu lệnh này. Gõ /help để xem danh sách lệnh.")

    def handle_callback(self, cq: dict) -> None:
        msg = cq.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        if chat not in self.allowed:
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text="Không có quyền")
            return
        action, _, ref = (cq.get("data") or "").partition(":")
        who = _who(cq.get("from"))
        if action == "silence":
            text = self.silence(who, ref)
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text=_plain(text)[:190])
            self.reply(chat, text, reply_to_message_id=msg.get("message_id"))
        elif action == "beep":
            text, ok = self.beep(ref, who)
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text=_plain(text)[:190])
            self.reply(chat, text, **({"reply_markup": STOP_BEEP} if ok else {}))
        elif action == "beepstop":
            text = self.stop_beep(who) or "Còi đã dừng rồi."
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text=_plain(text)[:190])
            self.api("editMessageReplyMarkup", chat_id=chat, message_id=msg.get("message_id"),
                     reply_markup={"inline_keyboard": []})
            self.reply(chat, text, reply_to_message_id=msg.get("message_id"))
        elif action == "uprestore":
            text = self.restore_upright(ref, who)
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text=_plain(text)[:190])
            self.api("editMessageReplyMarkup", chat_id=chat, message_id=msg.get("message_id"),
                     reply_markup={"inline_keyboard": []})
            self.reply(chat, text, reply_to_message_id=msg.get("message_id"))
        elif action == "ack":
            self.record(who, "ack", ref)
            self.api("answerCallbackQuery", callback_query_id=cq["id"], text="Đã ghi nhận")
            self.api("editMessageReplyMarkup", chat_id=chat, message_id=msg.get("message_id"),
                     reply_markup={"inline_keyboard": []})
            self.reply(chat, f"✅ <b>{escape(who)}</b> đã kiểm tra, người đeo ổn ({_hms(self.now())}).",
                       reply_to_message_id=msg.get("message_id"))
        else:
            self.api("answerCallbackQuery", callback_query_id=cq["id"])

    # ---------- thao tác ----------
    def dev(self) -> str:
        if self.status:
            return max(self.status, key=lambda d: self.status[d].get("_rx", 0))
        r = self.conn.execute("SELECT dev FROM predictions ORDER BY t DESC LIMIT 1").fetchone()
        return r["dev"] if r else "har01"

    def online(self, dev: str) -> bool | None:
        st = self.status.get(dev)
        if st is not None and st.get("online") is False:
            return False
        last = self.conn.execute("SELECT MAX(t) AS t FROM predictions WHERE dev = ?", (dev,)).fetchone()["t"]
        if last is not None and self.now() - last < ONLINE_MS:
            return True
        return None if st is None else bool(st.get("online"))

    def alarm_state(self, dev: str) -> tuple[str, dict | None]:
        """('pending', ev) đang trong cửa sổ chờ hủy; ('confirmed', ev) còi đang kêu sau xác nhận; ('idle', None)."""
        now = self.now()
        rows = self.conn.execute(
            "SELECT id, t, type, payload, received_at FROM device_events WHERE dev = ? AND received_at >= ? ORDER BY t",
            (dev, now - CONFIRMED_BUZZ_MS - PENDING_MS)).fetchall()
        state, ev = "idle", None
        for r in rows:
            if r["type"] == "suspected":
                state, ev = "pending", dict(r)
            elif r["type"] == "cancelled":
                state, ev = "idle", None
            elif r["type"] == "confirmed":
                state, ev = "confirmed", dict(r)
        if state == "pending" and now - ev["received_at"] > PENDING_MS:
            state = "idle"
        if state == "confirmed" and now - ev["received_at"] > CONFIRMED_BUZZ_MS:
            state = "idle"
        return state, ev

    def beep(self, arg: str, who: str) -> tuple[str, bool]:
        """Bật còi (lệnh beep của firmware). Trả (tin trả lời, đã gửi lệnh)."""
        dev = self.dev()
        try:
            secs = float(arg.replace(",", "."))
        except ValueError:
            return f"Cách dùng: /coi rồi chọn, hoặc /coi 20 (số giây, tối đa {MAX_BEEP_S}).", False
        secs = max(0.5, min(float(MAX_BEEP_S), secs))
        if self.online(dev) is False:
            return f"📴 Bộ đeo <code>{escape(dev)}</code> đang offline, không bật còi được.", False
        self.publish(f"har/{dev}/cmd", {"cmd": "beep", "ms": int(secs * 1000)})
        self.beep_until[dev] = self.now() + int(secs * 1000)
        self.record(who, "beep", f"{dev}:{secs:g}s")
        return (f"🔔 <b>{escape(who)}</b> đã bật còi {secs:g} giây trên <code>{escape(dev)}</code> "
                f"(tới {_hms(self.beep_until[dev])}). Nút trên bộ đeo không tắt được còi này; "
                "bấm Dừng còi hoặc gõ /tatcoi."), True

    def stop_beep(self, who: str) -> str | None:
        """Dừng còi /coi (beep 0 ms). Không đụng tới cảnh báo té. None nếu còi đã tự dừng."""
        dev = self.dev()
        if self.beep_until.get(dev, 0) <= self.now():
            return None
        self.publish(f"har/{dev}/cmd", {"cmd": "beep", "ms": 0})
        self.beep_until.pop(dev, None)
        self.record(who, "beep_stop", dev)
        return f"⏹ <b>{escape(who)}</b> đã dừng còi lúc {_hms(self.now())}."

    def silence(self, who: str, ref: str = "") -> str:
        dev = self.dev()
        stopped = self.stop_beep(who)
        state, ev = self.alarm_state(dev)
        if state == "pending":
            return ((stopped + "\n") if stopped else "") + (
                "⏳ Bộ đeo đang trong 10 s chờ người đeo tự hủy cảnh báo té (còn khoảng "
                f"{max(0, CANCEL_WINDOW_MS - (self.now() - ev['t'])) / 1000:.0f} s). Tắt từ xa lúc này sẽ "
                "<b>hủy luôn cảnh báo té</b>, nên bot không làm. Nếu người đeo ổn, họ nhấn nút trên bộ đeo.")
        if state == "idle":
            return stopped or "🔕 Hiện không có còi nào đang kêu."
        self.publish(f"har/{dev}/cmd", {"cmd": "cancel_alarm"})
        self.record(who, "silence", ref or ev["id"])
        return (f"🔕 <b>{escape(who)}</b> đã tắt còi lúc {_hms(self.now())}. "
                "Cảnh báo té vẫn được lưu; hãy liên lạc với người đeo.")

    def calibrate(self, chat: str, who: str) -> str:
        dev = self.dev()
        if self.online(dev) is False:
            return f"📴 Bộ đeo <code>{escape(dev)}</code> đang offline, không hiệu chỉnh được."
        if self.alarm_state(dev)[0] != "idle":
            return "⚠️ Bộ đeo đang cảnh báo té, chưa hiệu chỉnh lúc này."
        req = f"tg-{self.now() // 1000}"
        with self.lock:
            self.cal_pending[req] = {"chat": chat, "who": who, "dev": dev, "t": self.now()}
        self.publish(f"har/{dev}/cmd", {"cmd": "calibrate_upright", "id": req})
        self.record(who, "calibrate", req)
        return ("🧍 Người đeo hãy <b>đứng thẳng như bình thường và giữ yên khoảng 4 giây</b>. "
                "Bộ đeo đang đo, kết quả sẽ gửi về đây.")

    def restore_upright(self, ref: str, who: str) -> str:
        with self.lock:
            item = self.restore.pop(ref, None)
        if not item:
            return "Không còn hướng cũ để khôi phục (bot đã khởi động lại hoặc đã khôi phục rồi)."
        dev, old = item
        self.publish(f"har/{dev}/cmd", {"cmd": "set_upright", "up": [round(float(x), 4) for x in old]})
        self.record(who, "upright_restore", ref)
        return f"↩️ <b>{escape(who)}</b> đã khôi phục hướng đứng thẳng cũ cho <code>{escape(dev)}</code>."

    def on_calibration(self, dev: str, old: dict, st: dict) -> None:
        """Gọi khi status báo kết quả hiệu chỉnh mới: trả lời /hieuchinh hoặc báo lần người đeo nhấn nút."""
        req, res = st.get("upright_req") or "", st.get("upright_result")
        with self.lock:
            pend = self.cal_pending.pop(req, None)
        if pend:
            chat, src = pend["chat"], f"theo lệnh của <b>{escape(pend['who'])}</b>"
        elif req.startswith("btn-"):
            chat, src = self.cfg.telegram_chat_id, "bằng <b>nút trên bộ đeo</b> (nhấn 3 lần)"
        else:
            return  # record.py (thu dữ liệu) hoặc lệnh khác: không báo
        if res != "ok":
            why = CAL_FAIL.get(res, res)
            self.reply(chat, f"❌ Hiệu chỉnh hướng đứng {src} <b>chưa đạt</b> ({escape(str(why))}). Giữ hướng cũ.\n"
                             "Thử lại: người đeo đứng thẳng yên rồi gõ /hieuchinh, hoặc nhấn nút 3 lần.")
            return
        new, prev = st.get("upright"), old.get("upright")
        change, tilt = angle_deg(new, prev), angle_deg(new, UPRIGHT_DEFAULT)
        lines = [f"✅ Đã hiệu chỉnh hướng đứng thẳng {src} lúc {_hms(self.now())}."]
        if tilt is not None:
            lines.append(f"Nghiêng {tilt:.0f}° so với cách đeo chuẩn"
                         + (f", đổi {change:.0f}° so với hướng trước." if change is not None else "."))
        markup = {}
        if prev and change is not None and change >= 1:
            with self.lock:
                self.restore[req] = (dev, prev)
            markup = {"reply_markup": {"inline_keyboard": [[{"text": "↩️ Khôi phục hướng cũ",
                                                             "callback_data": f"uprestore:{req}"}]]}}
        if change is not None and change > UPRIGHT_WARN_DEG:
            lines.append(f"⚠️ Đổi hơn {UPRIGHT_WARN_DEG}°: nếu lúc đo người đeo không đứng thẳng (đang ngồi, nằm, cúi), "
                         "bấm Khôi phục rồi hiệu chỉnh lại.")
        self.record("bộ đeo" if req.startswith("btn-") else (pend or {}).get("who", ""), "calibrated", req)
        self.reply(chat, "\n".join(lines), **markup)

    def check_timeouts(self) -> None:
        now = self.now()
        with self.lock:
            late = [(k, v) for k, v in self.cal_pending.items() if now - v["t"] > CAL_TIMEOUT_MS]
            for k, _ in late:
                self.cal_pending.pop(k, None)
        for _, v in late:
            self.reply(v["chat"], "⌛ Không nhận được kết quả hiệu chỉnh từ bộ đeo. Kiểm tra kết nối rồi thử lại /hieuchinh.")

    def record(self, who: str, action: str, ref: str) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO bot_actions (t, who, action, ref) VALUES (?, ?, ?, ?)",
                              (self.now(), who, action, ref))

    # ---------- nội dung ----------
    def status_text(self) -> str:
        dev, now = self.dev(), self.now()
        on = self.online(dev)
        lines = [f"<b>Trạng thái</b> · <code>{escape(dev)}</code>",
                 {True: "🟢 Đang kết nối", False: "📴 Mất kết nối", None: "⚪ Chưa rõ kết nối"}[on]]
        last = self.conn.execute(
            "SELECT t, COALESCE(smoothed, label) AS l, conf FROM predictions WHERE dev = ? ORDER BY t DESC LIMIT 1",
            (dev,)).fetchone()
        if last:
            since = last["t"]
            for r in self.conn.execute("SELECT t, COALESCE(smoothed, label) AS l FROM predictions "
                                       "WHERE dev = ? AND t <= ? ORDER BY t DESC LIMIT 43200", (dev, last["t"])):
                if r["l"] != last["l"] or since - r["t"] > GAP_MS:
                    break
                since = r["t"]
            label = VI.get(last["l"], last["l"])
            if on:
                lines.append(f"Đang: <b>{label}</b> ({(last['conf'] or 0):.0%}) từ {_hm(since)}, được {_dur(now - since)}")
            else:
                lines.append(f"Lần cuối thấy: <b>{label}</b> lúc {_hm(last['t'])}")
        state, ev = self.alarm_state(dev)
        if state == "pending":
            lines.append("⚠️ Bộ đeo đang nghi té, chờ người đeo hủy")
        elif state == "confirmed":
            lines.append("🚨 Đang cảnh báo té (còi kêu)")
        a = self.conn.execute("SELECT t, type, payload FROM alerts WHERE dev = ? AND type IN ('fall', 'sos') "
                              "ORDER BY t DESC LIMIT 1", (dev,)).fetchone()
        if a:
            p = json.loads(a["payload"])
            kind = "SOS" if a["type"] == "sos" else ("té đã hủy" if p.get("cancelled") else "té")
            lines.append(f"Cảnh báo gần nhất: {kind} lúc {_hm(a['t'])} {datetime.fromtimestamp(a['t'] / 1000):%d/%m}")
        st = self.status.get(dev) or {}
        extra = []
        if st.get("rssi") is not None:
            extra.append(f"Wi-Fi {st['rssi']} dBm")
        if st.get("uptime_s") is not None:
            extra.append(f"bật {_dur(st['uptime_s'] * 1000)}")
        extra.append("pin: không đo được" if st.get("battery_v") is None else f"pin {st['battery_v']:.2f} V")
        lines.append(" · ".join(extra))
        return "\n".join(lines)

    def today_text(self) -> str:
        dev, now = self.dev(), self.now()
        t0 = _start_of_day(now)
        rows = self.conn.execute("SELECT t, COALESCE(smoothed, label) AS l FROM predictions "
                                 "WHERE dev = ? AND t >= ? ORDER BY t", (dev, t0)).fetchall()
        tot: dict[str, float] = {}
        for a, b in zip(rows, rows[1:]):
            dt = b["t"] - a["t"]
            if 0 < dt <= GAP_MS:
                tot[a["l"]] = tot.get(a["l"], 0) + dt
        lines = [f"<b>Hôm nay</b> {datetime.fromtimestamp(now / 1000):%d/%m} · <code>{escape(dev)}</code>"]
        worn = sum(tot.values())
        if not worn:
            lines.append("Chưa có dữ liệu hoạt động hôm nay.")
        else:
            lines.append(f"Thời gian đeo có dữ liệu: {_dur(worn)}")
            for k in ORDER:
                if tot.get(k, 0) >= 1000 and k != "fall":
                    lines.append(f"• {VI[k]}: {_dur(tot[k])} ({tot[k] / worn:.0%})")
        al = self.conn.execute("SELECT type, payload FROM alerts WHERE dev = ? AND t >= ?", (dev, t0)).fetchall()
        falls = [json.loads(r["payload"]) for r in al if r["type"] == "fall"]
        real = sum(1 for p in falls if not p.get("cancelled"))
        cancelled = len(falls) - real
        sos = sum(1 for r in al if r["type"] == "sos")
        off = sum(1 for r in al if r["type"] == "offline")
        lines.append(f"Cảnh báo té: {real} · té đã hủy: {cancelled} · SOS: {sos} · mất kết nối: {off}")
        lines.append("<i>Số liệu theo model dự đoán, có sai số.</i>")
        return "\n".join(lines)

    # ---------- MQTT ----------
    def on_status(self, topic: str, payload: dict) -> None:
        dev, kind = topic_parts(topic)
        if kind != "status" or not dev:
            return
        old = self.status.get(dev)
        self.status[dev] = {**old, **payload, "_rx": self.now()} if old else {**payload, "_rx": self.now()}
        key = (payload.get("upright_req"), payload.get("upright_result"))
        if old is None:  # status đầu tiên (retained) lúc bot vừa chạy: kết quả cũ, không báo lại
            self.cal_done[dev] = key
            return
        if key[0] is None or key[1] in (None, "none", "pending") or self.cal_done.get(dev) == key:
            return
        self.cal_done[dev] = key
        try:
            self.on_calibration(dev, old or {}, payload)
        except Exception:
            log.exception("Lỗi báo kết quả hiệu chỉnh")


def _plain(html_text: str) -> str:
    return re.sub(r"<[^>]+>", "", html_text)


def main() -> None:
    setup_logging()  # che token Telegram, tắt log từng request của httpx
    cfg = load_config()
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        log.error("Chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — har-bot không chạy")
        return
    conn = store.connect(cfg.db_path)
    bot = Bot(cfg, conn, publish=lambda t, p: publish_json(client, t, p, qos=1))
    client = make_client(cfg, "har-bot", [("har/+/status", 0)], bot.on_status)
    client.loop_start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    fails, registered = 0, False
    while not stop.is_set():
        try:
            if not registered:
                bot.register_commands()  # menu lệnh trong Telegram
                registered = True
            bot.poll_once(timeout=10)
            bot.check_timeouts()
            fails = 0
        except Exception:
            fails += 1
            log.exception("Lỗi vòng bot")
            stop.wait(min(60, 2**fails))
    client.loop_stop()


if __name__ == "__main__":
    main()
