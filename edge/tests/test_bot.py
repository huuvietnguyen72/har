"""har-bot: lệnh Telegram (Telegram và MQTT giả lập)."""
import json
from datetime import datetime

import httpx
import pytest

from har_edge import store
from har_edge.bot import Bot, fall_buttons
from har_edge.config import Config
from har_edge.notify import Notifier

CHAT = "5198222263"
NOW = int(datetime(2026, 11, 19, 20, 0, 0).timestamp() * 1000)


@pytest.fixture()
def env(tmp_path):
    conn = store.connect(tmp_path / "edge.db")
    calls, published = [], []

    def handler(req):
        calls.append((req.url.path.rsplit("/", 1)[-1], json.loads(req.content)))
        return httpx.Response(200, json={"ok": True, "result": []})

    cfg = Config(telegram_bot_token="t", telegram_chat_id=CHAT)
    clock = {"now": NOW}
    bot = Bot(cfg, conn, publish=lambda t, p: published.append((t, p)),
              client=httpx.Client(transport=httpx.MockTransport(handler)), now=lambda: clock["now"])
    return bot, conn, calls, published, clock


def msg(text, chat=CHAT, t=NOW):
    return {"update_id": 1, "message": {"message_id": 7, "date": t // 1000, "text": text, "chat": {"id": int(chat)},
                                        "from": {"id": 1, "first_name": "Viet"}}}


def sent_texts(calls):
    return [b["text"] for m, b in calls if m == "sendMessage"]


def add_preds(conn, t0, labels, dev="har01", step=1000):
    for i, l in enumerate(labels):
        conn.execute("INSERT INTO predictions (dev, t, label, smoothed, conf, p_fall, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (dev, t0 + i * step, l, l, 0.8, 0.0, "rf"))


def add_event(conn, typ, t, eid, dev="har01"):
    conn.execute("INSERT INTO device_events (id, dev, t, type, payload, received_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (eid, dev, t, typ, json.dumps({"id": eid, "type": typ, "t": t}), t + 300))


def test_ignores_other_chats_and_stale_commands(env):
    bot, conn, calls, published, _ = env
    bot.handle_update(msg("/coi", chat="999"))
    bot.handle_update(msg("/coi", t=NOW - 10 * 60_000))  # gửi lúc bot đang tắt
    assert published == [] and calls == []


def test_beep_menu_options_and_stop(env):
    bot, conn, calls, published, clock = env
    bot.handle_update(msg("/coi"))  # không có số giây -> hiện lựa chọn, chưa kêu
    assert published == []
    menu = [b for m, b in calls if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in menu] == ["beep:5", "beep:30", "beep:60"]
    cq = {"id": "q", "data": "beep:30", "from": {"first_name": "Viet"}, "message": {"message_id": 3, "chat": {"id": int(CHAT)}}}
    bot.handle_update({"update_id": 2, "callback_query": cq})
    assert published == [("har/har01/cmd", {"cmd": "beep", "ms": 30000})]
    assert [b for m, b in calls if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "beepstop"
    clock["now"] = NOW + 10_000
    bot.handle_update({"update_id": 3, "callback_query": {**cq, "data": "beepstop"}})
    assert published[-1] == ("har/har01/cmd", {"cmd": "beep", "ms": 0})  # dừng còi, không cancel_alarm
    bot.handle_update({"update_id": 4, "callback_query": {**cq, "data": "beepstop"}})
    assert len(published) == 2 and "đã dừng rồi" in sent_texts(calls)[-1]
    assert [r[0] for r in conn.execute("SELECT action FROM bot_actions ORDER BY id")] == ["beep", "beep_stop"]


def test_tatcoi_stops_beep_but_never_cancels_pending_fall(env):
    bot, conn, calls, published, clock = env
    bot.handle_update(msg("/coi 60"))
    add_event(conn, "suspected", NOW + 2000, "har01-9")
    clock["now"] = NOW + 4000
    bot.handle_update(msg("/tatcoi", t=clock["now"]))
    assert published == [("har/har01/cmd", {"cmd": "beep", "ms": 60000}), ("har/har01/cmd", {"cmd": "beep", "ms": 0})]
    assert "đã dừng còi" in sent_texts(calls)[-1] and "hủy luôn cảnh báo té" in sent_texts(calls)[-1]


def test_beep_capped_and_offline(env):
    bot, conn, calls, published, _ = env
    bot.handle_update(msg("/coi 5"))
    bot.handle_update(msg("/coi@harnoti_bot 999"))
    assert published == [("har/har01/cmd", {"cmd": "beep", "ms": 5000}), ("har/har01/cmd", {"cmd": "beep", "ms": 60000})]
    assert conn.execute("SELECT COUNT(*) FROM bot_actions WHERE action = 'beep'").fetchone()[0] == 2
    bot.handle_update(msg("/coi abc"))
    assert len(published) == 2 and "Cách dùng" in sent_texts(calls)[-1]
    bot.on_status("har/har01/status", {"v": 1, "online": False})
    bot.handle_update(msg("/coi 5"))
    assert len(published) == 2 and "offline" in sent_texts(calls)[-1]


def test_silence_refused_while_wearer_can_cancel(env):
    bot, conn, calls, published, clock = env
    add_event(conn, "suspected", NOW - 3000, "har01-1")
    bot.handle_update(msg("/tatcoi"))
    assert published == [] and "hủy luôn cảnh báo té" in sent_texts(calls)[-1]
    add_event(conn, "confirmed", NOW + 7000, "har01-2")  # hết 10 s, còi kêu 30 s
    clock["now"] = NOW + 9000
    bot.handle_update(msg("/tatcoi", t=clock["now"]))
    assert published == [("har/har01/cmd", {"cmd": "cancel_alarm"})]
    assert "Viet</b> đã tắt còi" in sent_texts(calls)[-1]
    clock["now"] = NOW + 60_000  # còi đã tự tắt
    bot.handle_update(msg("/tatcoi", t=clock["now"]))
    assert len(published) == 1 and "không có còi" in sent_texts(calls)[-1]


def test_silence_idle_after_cancelled(env):
    bot, conn, calls, published, _ = env
    add_event(conn, "suspected", NOW - 6000, "a")
    add_event(conn, "cancelled", NOW - 3000, "b")
    assert bot.alarm_state("har01")[0] == "idle"


def test_today_and_status(env):
    bot, conn, calls, published, _ = env
    start = NOW - 3600_000
    add_preds(conn, start, ["walk"] * 600)                       # 10 phút đi bộ
    add_preds(conn, start + 1200_000, ["sit"] * 300)              # khoảng trống 10 phút không tính
    add_preds(conn, NOW - 120_000, ["lie"] * 118)                 # đang nằm 2 phút
    a = {"id": "x", "dev": "har01", "t": start + 5000, "type": "fall", "cancelled": True}
    conn.execute("INSERT INTO alerts (id, dev, t, type, payload, notify, created_at) VALUES ('x', 'har01', ?, 'fall', ?, 0, ?)",
                 (start + 5000, json.dumps(a), start))
    bot.handle_update(msg("/homnay"))
    text = sent_texts(calls)[-1]
    assert "Đi bộ: 9 phút" in text and "Ngồi: 4 phút" in text and "Nằm: 1 phút" in text
    assert "té đã hủy: 1" in text and "Cảnh báo té: 0" in text
    bot.handle_update(msg("/trangthai"))
    text = sent_texts(calls)[-1]
    assert "Đang kết nối" in text and "<b>Nằm</b>" in text and "từ 19:58, được 2 phút" in text
    assert "pin: không đo được" in text


def test_ack_button_and_unauthorized_callback(env):
    bot, conn, calls, published, _ = env
    cq = {"id": "q1", "data": "ack:har01-1", "from": {"first_name": "Viet"},
          "message": {"message_id": 9, "chat": {"id": int(CHAT)}}}
    bot.handle_update({"update_id": 2, "callback_query": cq})
    methods = [m for m, _ in calls]
    assert methods == ["answerCallbackQuery", "editMessageReplyMarkup", "sendMessage"]
    assert conn.execute("SELECT who, action, ref FROM bot_actions").fetchone()[:] == ("Viet", "ack", "har01-1")
    calls.clear()
    bot.handle_update({"update_id": 3, "callback_query": {**cq, "message": {"message_id": 9, "chat": {"id": 1}}}})
    assert calls == [("answerCallbackQuery", {"callback_query_id": "q1", "text": "Không có quyền"})]


def test_notify_attaches_buttons_to_fall_alerts(tmp_path):
    conn = store.connect(tmp_path / "edge.db")
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True})

    n = Notifier(Config(telegram_bot_token="t", telegram_chat_id=CHAT), conn,
                 client=httpx.Client(transport=httpx.MockTransport(handler)))
    for aid, typ in (("har01-5", "fall"), ("har01-offline-1", "offline")):
        a = {"id": aid, "dev": "har01", "t": NOW, "type": typ, "severity": "high", "source": "both", "cancelled": False}
        conn.execute("INSERT INTO alerts (id, dev, t, type, payload, notify, created_at) VALUES (?, 'har01', ?, ?, ?, 1, ?)",
                     (aid, NOW + (typ == "offline") * 70_000, typ, json.dumps(a), NOW))
    n.step(NOW + 80_000)
    fall = [b for b in bodies if "TÉ" in b["text"]][0]
    assert fall["reply_markup"] == fall_buttons("har01-5")
    assert all("reply_markup" not in b for b in bodies if "mất kết nối" in b["text"])
