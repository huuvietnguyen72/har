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


def test_logs_never_contain_bot_token(capsys):
    import logging

    from har_edge.logutil import setup_logging

    setup_logging()
    tok = "1234567890:FAKE-token_for_tests_only_xxxxxxxx"  # token giả, không phải token thật
    log = logging.getLogger("har-bot")
    logging.getLogger("httpx").info("HTTP Request: POST https://api.telegram.org/bot%s/getUpdates", tok)
    try:
        raise httpx.ConnectError(f"lỗi https://api.telegram.org/bot{tok}/sendMessage")
    except httpx.ConnectError:
        log.exception("Lỗi vòng bot")
    err = capsys.readouterr().err
    assert tok not in err and "bot<token-ẩn>" in err and "HTTP Request" not in err


def test_hieuchinh_command_result_and_restore(env):
    bot, conn, calls, published, clock = env
    old = [-0.924, -0.201, -0.327]
    bot.on_status("har/har01/status", {"online": True, "upright": old, "upright_req": "rec-1", "upright_result": "ok"})
    assert calls == []  # status giữ lại lúc bot vừa chạy: không báo
    bot.handle_update(msg("/hieuchinh"))
    req = published[-1][1]["id"]
    assert published[-1] == ("har/har01/cmd", {"cmd": "calibrate_upright", "id": req}) and req.startswith("tg-")
    assert "đứng thẳng" in sent_texts(calls)[-1]
    new = [-0.99, 0.0, -0.14]
    st = {"online": True, "upright": new, "upright_req": req, "upright_result": "ok"}
    bot.on_status("har/har01/status", st)
    bot.on_status("har/har01/status", st)  # status lặp lại mỗi 10 s: không báo hai lần
    texts = [t for t in sent_texts(calls) if "Đã hiệu chỉnh" in t]
    assert len(texts) == 1 and "theo lệnh của <b>Viet</b>" in texts[0] and "Nghiêng 8°" in texts[0]
    body = [b for m, b in calls if m == "sendMessage"][-1]
    assert body["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"uprestore:{req}"
    cq = {"id": "q", "data": f"uprestore:{req}", "from": {"first_name": "Viet"},
          "message": {"message_id": 5, "chat": {"id": int(CHAT)}}}
    bot.handle_update({"update_id": 9, "callback_query": cq})
    assert published[-1] == ("har/har01/cmd", {"cmd": "set_upright", "up": old})
    bot.handle_update({"update_id": 10, "callback_query": cq})  # bấm lần hai: không gửi lại
    assert published[-1][1]["cmd"] == "set_upright" and len([p for p in published if p[1]["cmd"] == "set_upright"]) == 1


def test_button_calibration_reported_and_failures(env):
    bot, conn, calls, published, clock = env
    bot.on_status("har/har01/status", {"online": True, "upright": [-1, 0, 0], "upright_req": "", "upright_result": "none"})
    bot.on_status("har/har01/status", {"online": True, "upright": [-1, 0, 0], "upright_req": "x", "upright_result": "none"})
    # người đeo nhấn nút 3 lần nhưng đang cử động
    bot.on_status("har/har01/status", {"online": True, "upright": [-1, 0, 0], "upright_req": "btn-100", "upright_result": "moving"})
    assert "nút trên bộ đeo" in sent_texts(calls)[-1] and "chưa đạt" in sent_texts(calls)[-1]
    assert conn.execute("SELECT who, action, ref FROM bot_actions").fetchall()[-1][:] == ("bộ đeo", "calibrate_fail:moving", "btn-100")
    # lần sau đạt, nhưng đổi > 45° (vd đang nằm): cảnh báo
    bot.on_status("har/har01/status", {"online": True, "upright": [0, 0, -1], "upright_req": "btn-200", "upright_result": "ok"})
    t = sent_texts(calls)[-1]
    assert "Đã hiệu chỉnh" in t and "đổi 90°" in t and "⚠️" in t
    n = len(calls)
    bot.on_status("har/har01/status", {"online": True, "upright": [-1, 0, 0], "upright_req": "rec-5", "upright_result": "ok"})
    assert len(calls) == n  # record.py: không báo


def test_hieuchinh_timeout(env):
    bot, conn, calls, published, clock = env
    bot.handle_update(msg("/hieuchinh"))
    clock["now"] = NOW + 30_000
    bot.check_timeouts()
    assert "Không nhận được kết quả" in sent_texts(calls)[-1] and bot.cal_pending == {}


def test_thu_stairs_session_buttons(env):
    bot, conn, calls, published, clock = env
    bot.on_status("har/har01/status", {"online": True, "upright": [-0.9, -0.08, -0.43], "upright_cal": "measured"})
    bot.handle_update(msg("/thu T01 stairs_up vitri=A"))
    start = [p for t, p in published if t == "har/har01/session"][-1]
    assert start["action"] == "start" and start["subject"] == "T01" and start["activity"] == "stairs_up"
    assert start["note"] == "vitri=A" and start["upright"] == [-0.9, -0.08, -0.43] and 20 < start["upright_angle_deg"] < 30
    assert ("har/har01/cmd", {"cmd": "display", "mode": "record", "activity": "stairs_up"}) in published
    bot.handle_update(msg("/thu T01 walk"))  # đang thu: không mở phiên thứ hai
    assert len([1 for t, p in published if t == "har/har01/session"]) == 1 and "Đang thu" in sent_texts(calls)[-1]
    cq = {"id": "q", "data": "rec:stop", "from": {"first_name": "Viet"}, "message": {"message_id": 4, "chat": {"id": int(CHAT)}}}
    clock["now"] = NOW + 15_000
    bot.handle_update({"update_id": 2, "callback_query": cq})
    stop = [p for t, p in published if t == "har/har01/session"][-1]
    assert stop == {"action": "stop", "id": start["id"]}
    assert ("har/har01/cmd", {"cmd": "cancel_alarm"}) in published
    after = [b for m, b in calls if m == "sendMessage"][-1]
    assert [b["callback_data"] for b in after["reply_markup"]["inline_keyboard"][0]] == ["rec:again", "rec:flip"]
    clock["now"] = NOW + 20_000
    bot.handle_update({"update_id": 3, "callback_query": {**cq, "data": "rec:flip"}})  # đổi chiều: xuống
    flip = [p for t, p in published if t == "har/har01/session"][-1]
    assert flip["action"] == "start" and flip["activity"] == "stairs_down" and flip["note"] == "vitri=A"
    assert flip["id"] != start["id"]
    clock["now"] = NOW + 20_000 + 11 * 60_000  # quên dừng
    bot.check_timeouts()
    assert [p for t, p in published if t == "har/har01/session"][-1]["action"] == "stop" and bot.rec is None
    assert "tự dừng" in sent_texts(calls)[-1]


def test_thu_usage_and_stop_without_session(env):
    bot, conn, calls, published, _ = env
    bot.handle_update(msg("/thu T01 nhay"))
    assert published == [] and "Cách dùng" in sent_texts(calls)[-1]
    bot.handle_update(msg("/dung"))  # bot vừa khởi động lại: vẫn gửi lệnh dừng cho har-ingest
    assert ("har/har01/session", {"action": "stop", "id": None}) in published


def test_multiple_recipients_command_and_button_calibration(tmp_path):
    """TELEGRAM_CHAT_ID nhiều người: ai cũng ra lệnh được; hiệu chỉnh bằng nút trên bộ đeo báo cho tất cả."""
    conn = store.connect(tmp_path / "edge.db")
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append((req.url.path.rsplit("/", 1)[-1], body))
        if str(body.get("chat_id")) == "888":  # người này chặn bot: không làm hỏng tin của người khác
            return httpx.Response(403, json={"ok": False, "description": "Forbidden: bot was blocked by the user"})
        return httpx.Response(200, json={"ok": True, "result": []})

    bot = Bot(Config(telegram_bot_token="t", telegram_chat_id=f"{CHAT}, 777,888"), conn, publish=lambda t, p: None,
              client=httpx.Client(transport=httpx.MockTransport(handler)), now=lambda: NOW)
    bot.handle_update(msg("/trangthai", chat="777"))
    assert [b["chat_id"] for m, b in calls if m == "sendMessage"] == ["777"]
    calls.clear()
    bot.on_status("har/har01/status", {"online": True, "upright": [-1, 0, 0], "upright_req": "", "upright_result": "none"})
    bot.on_status("har/har01/status", {"online": True, "upright": [-1, 0, 0], "upright_req": "btn-1", "upright_result": "moving"})
    assert sorted(str(b["chat_id"]) for m, b in calls if m == "sendMessage") == sorted([CHAT, "777", "888"])

