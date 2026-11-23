"""Logic thuần (không MQTT, không I/O) của har-infer — có unit test.

- stairs_gate: bỏ nhãn cầu thang khi độ cao không đổi trong ~10 s (áp suất BMP280)
- Smoother   : đa số 3 dự đoán gần nhất, nhãn té không làm mượt
- Segmenter  : gộp dự đoán thành đoạn hoạt động (start, end, label, conf_avg)
- FallFusion : hợp nhất cảnh báo té giữa ngưỡng trên ESP32 và model trên Pi
- TechMonitor: cảnh báo kỹ thuật (pin yếu, mất kết nối)

Mọi hàm nhận thời gian qua tham số (epoch ms) để test được.
"""
from collections import Counter, deque
from dataclasses import dataclass, field

import numpy as np

from .features import PA_PER_METER


STAIRS = ("stairs_up", "stairs_down")


def stairs_gate(probs: dict[str, float], alt_change_m: float | None, min_m: float) -> dict[str, float]:
    """Không cho nhãn cầu thang khi độ cao gần như không đổi trong ~10 s (|Δ| < min_m).

    Đứng/đi trên mặt phẳng: |Δcao 10 s| trung vị 0,09–0,11 m; leo cầu thang: 1,5–1,7 m (dataset S02–S04). Chỉ đặt
    xác suất cầu thang về 0, KHÔNG chia lại tỉ lệ, để P(té) không bị đẩy lên giả tạo. None (chưa đủ 10 s áp suất)
    hoặc min_m <= 0: giữ nguyên.
    """
    if alt_change_m is None or min_m <= 0 or abs(alt_change_m) >= min_m:
        return probs
    if max(probs, key=probs.get) not in STAIRS:
        return probs
    return {k: (0.0 if k in STAIRS else v) for k, v in probs.items()}


def altitude_change_m(p: np.ndarray, t_end: float, span_ms: int = 10_000, avg_ms: int = 1_000) -> float | None:
    """Độ cao thay đổi (m, dương = lên) trong span_ms kết thúc ở t_end, từ mảng (t, Pa); trung bình 1 s ở hai đầu
    để bớt nhiễu. None nếu chưa có đủ dữ liệu."""
    if p is None or len(p) < 4:
        return None
    t, pa = p[:, 0], p[:, 1]
    start = t_end - span_ms
    if t[0] > start + 2000:
        return None
    first = pa[(t >= start) & (t < start + avg_ms)]
    last = pa[(t > t_end - avg_ms) & (t <= t_end)]
    if len(first) == 0 or len(last) == 0:
        return None
    return float((first.mean() - last.mean()) / PA_PER_METER)


class Smoother:
    def __init__(self, n: int = 3):
        self.hist: deque[str] = deque(maxlen=n)
        self.current: str | None = None

    def update(self, label: str) -> str:
        if label == "fall":
            return "fall"
        self.hist.append(label)
        top, cnt = Counter(self.hist).most_common(1)[0]
        if cnt >= 2 or self.current is None:
            self.current = top
        return self.current


@dataclass
class Segmenter:
    dev: str
    label: str | None = None
    start: int = 0
    last_t: int = 0
    confs: list[float] = field(default_factory=list)

    def update(self, t: int, label: str, conf: float) -> dict | None:
        closed = None
        if self.label is not None and label != self.label:
            closed = self._close(t)
        if self.label is None:
            self.label, self.start, self.confs = label, t, []
        self.confs.append(conf)
        self.last_t = t
        return closed

    def _close(self, end: int) -> dict:
        seg = {
            "dev": self.dev, "start": self.start, "end": end, "label": self.label,
            "conf_avg": round(sum(self.confs) / len(self.confs), 3) if self.confs else None,
        }
        self.label = None
        self.confs = []
        return seg

    def flush(self, end: int | None = None) -> dict | None:
        """Đóng đoạn đang mở (khi thiết bị mất kết nối hoặc dịch vụ dừng)."""
        if self.label is None:
            return None
        return self._close(end if end is not None else self.last_t)


@dataclass
class FusionParams:
    p_confirm: float = 0.5  # model ≥ ngưỡng này khi ESP32 đã báo -> mức cao
    # model tự báo khi ESP32 không kích hoạt. 0,5 chọn theo thí nghiệm D 18/11: RF (tự thu + SisFall) cho
    # P(té) 0,50–0,70 ở cả 23 cú té S01, nên 0,8 không bao giờ kích hoạt (xem docs/firmware-integration.md mục 19)
    p_model_only: float = 0.5
    lie_after_s: float = 5.0  # ... và sau đó nằm ít nhất ngần này giây
    window_ms: int = 3000  # ±3 s quanh va chạm
    pending_timeout_ms: int = 15000  # suspected mà không thấy confirmed/cancelled -> coi như confirmed
    # model không tự báo nếu ngay trước đó đang nằm (trở mình trên giường không phải té)
    skip_if_lying: bool = True
    # Model phát hiện té mà bộ đeo không kích hoạt: Pi ra lệnh test_alarm để bộ đeo kêu còi và cho người đeo
    # 10 s tự hủy, như khi bộ đeo tự phát hiện. Bộ đeo không phản hồi (mất kết nối, hết pin) trong khoảng này
    # thì Pi báo thẳng, để không mất cảnh báo.
    device_alarm_timeout_ms: int = 15000
    device_alarm_link_ms: int = 8000  # "suspected" (peak_g 0) tới trong khoảng này sau lệnh -> do lệnh của Pi


class FallFusion:
    def __init__(self, dev: str, params: FusionParams | None = None):
        self.dev = dev
        self.p = params or FusionParams()
        self.preds: deque[tuple[int, float, str]] = deque(maxlen=120)  # (t, p_fall, label)
        self.incidents: dict[str, dict] = {}
        self.done: set[str] = set()
        self.candidate: dict | None = None
        self.model_requests: dict[str, dict] = {}  # id cảnh báo model -> {t, p, requested}: chờ bộ đeo bật còi
        self.commands: list[dict] = []  # lệnh gửi bộ đeo (har/{dev}/cmd), infer lấy bằng pop_commands()
        self.alert_of: dict[str, str] = {}  # id "suspected" của bộ đeo -> id cảnh báo (nhánh model: har01-m<t>)
        self.pending_ack: dict[str, int] = {}  # người đeo bấm nút trước khi cảnh báo chốt: id suspected -> lúc bấm

    def pop_commands(self) -> list[dict]:
        out, self.commands = self.commands, []
        return out

    # ---------- tiện ích ----------
    def _p_fall_near(self, t: int) -> float | None:
        ps = [p for (tp, p, _) in self.preds if abs(tp - t) <= self.p.window_ms]
        return max(ps) if ps else None

    def _prev_label(self, t: int) -> str | None:
        for tp, _, lbl in reversed(self.preds):
            if tp < t - 1000 and lbl != "fall":
                return lbl
        return None

    def _alert(self, aid: str, t: int, typ: str, severity: str, source: str, prob, cancelled=False, notify=True) -> dict:
        self.done.add(aid)
        return {
            "id": aid, "dev": self.dev, "t": t, "type": typ, "severity": severity, "source": source,
            "prob": None if prob is None else round(float(prob), 3), "prev_label": self._prev_label(t),
            "cancelled": cancelled, "notify": notify,
        }

    def _finalize(self, inc: dict, reason: str) -> dict:
        m = inc.get("model")
        if m:  # bộ đeo kêu theo lệnh của Pi (model phát hiện), người đeo không hủy -> mức cao
            self.done.add(inc["id"])
            a = self._alert(m["id"], m["t"], "fall", "high", "model", m["p"])
        else:
            p = self._p_fall_near(inc["t"])
            high = p is not None and p >= self.p.p_confirm
            a = self._alert(inc["id"], inc["t"], "fall", "high" if high else "medium", "both" if high else "threshold", p)
            a["peak_g"] = inc.get("peak_g")
        a["reason"] = reason
        self.alert_of[inc["id"]] = a["id"]
        if inc["id"] in self.pending_ack:
            a["wearer_ack_at"] = self.pending_ack.pop(inc["id"])
        return a

    def on_wearer_ack(self, ev: dict) -> str | None:
        """Sự kiện "silenced": người đeo nhấn nút sau khi té đã xác nhận (còi tắt, cảnh báo vẫn giữ).

        Trả id cảnh báo cần gắn "người đeo đã bấm nút", hoặc None nếu cảnh báo chưa chốt (giữ lại, gắn khi chốt).
        """
        ref = ev.get("ref")
        if not ref:
            return None
        if ref in self.alert_of:
            return self.alert_of[ref]
        if ref in self.incidents:  # confirmed chưa tới hoặc chưa hết giờ chờ: gắn khi _finalize
            self.pending_ack[ref] = int(ev.get("t") or 0)
            return None
        return ref  # Pi vừa khởi động lại: nhánh ngưỡng dùng chính id suspected làm id cảnh báo

    # ---------- đầu vào ----------
    def on_device_event(self, ev: dict, now: int) -> list[dict]:
        typ = ev.get("type")
        out: list[dict] = []
        if typ == "sos":
            if ev["id"] not in self.done:
                out.append(self._alert(ev["id"], ev["t"], "sos", "high", "device", None))
        elif typ == "suspected":
            if ev["id"] not in self.done and ev["id"] not in self.incidents:
                inc = {"id": ev["id"], "t": ev["t"], "peak_g": ev.get("peak_g"), "received": now}
                req = next((r for r in self.model_requests.values()
                            if 0 <= now - r["requested"] <= self.p.device_alarm_link_ms), None)
                if req is not None:
                    del self.model_requests[req["id"]]
                    if not ev.get("peak_g"):  # test_alarm (không có va chạm): cảnh báo do model yêu cầu
                        inc["model"] = req
                    # có va chạm thật: ngưỡng và model cùng thấy -> xử lý như incident ngưỡng thường
                self.incidents[ev["id"]] = inc
            if self.candidate and abs(self.candidate["t"] - ev["t"]) <= 5000:
                self.candidate = None  # model và ngưỡng cùng thấy -> để incident xử lý
        elif typ in ("cancelled", "confirmed"):
            ref = ev.get("ref") or ev["id"]
            inc = self.incidents.pop(ref, None) or {"id": ref, "t": ev.get("t_impact", ev["t"]), "peak_g": ev.get("peak_g")}
            if ref in self.done:
                return out
            if typ == "cancelled":
                m = inc.get("model")
                if m:  # người đeo hủy cảnh báo do model yêu cầu
                    self.done.add(ref)
                    a = self._alert(m["id"], m["t"], "fall", "info", "model", m["p"], cancelled=True, notify=False)
                else:
                    a = self._alert(ref, inc["t"], "fall", "info", "threshold", self._p_fall_near(inc["t"]),
                                    cancelled=True, notify=False)
                out.append(a)
            else:
                out.append(self._finalize(inc, "confirmed"))
        return out

    def on_prediction(self, t: int, p_fall: float, label: str, now: int) -> list[dict]:
        self.preds.append((t, p_fall, label))
        out: list[dict] = []
        near_incident = any(abs(i["t"] - t) <= 5000 for i in self.incidents.values())
        lying_before = self.p.skip_if_lying and self._prev_label(t) == "lie"
        if self.candidate is None and p_fall >= self.p.p_model_only and not near_incident and not lying_before:
            self.candidate = {"t": t, "p": p_fall, "lie_start": None}
        elif self.candidate is not None:
            c = self.candidate
            c["p"] = max(c["p"], p_fall) if t - c["t"] <= self.p.window_ms else c["p"]
            if label == "lie":
                c["lie_start"] = c["lie_start"] or t
                if t - c["lie_start"] >= self.p.lie_after_s * 1000:
                    aid = f"{self.dev}-m{c['t']}"
                    self.candidate = None
                    if aid not in self.done and aid not in self.model_requests:
                        # chưa báo ngay: nhờ bộ đeo kêu còi + 10 s cho người đeo hủy (xem device_alarm_timeout_ms)
                        self.model_requests[aid] = {"id": aid, "t": c["t"], "p": c["p"], "requested": now}
                        self.commands.append({"cmd": "test_alarm"})
            elif label != "fall":
                c["lie_start"] = None
            if self.candidate is not None and t - c["t"] > 15000:
                self.candidate = None
        return out

    def tick(self, now: int) -> list[dict]:
        out = []
        for aid, req in list(self.model_requests.items()):
            if now - req["requested"] > self.p.device_alarm_timeout_ms:  # bộ đeo không phản hồi -> báo thẳng
                del self.model_requests[aid]
                if aid not in self.done:
                    a = self._alert(aid, req["t"], "fall", "medium", "model", req["p"])
                    a["reason"] = "device_no_response"
                    out.append(a)
        for iid, inc in list(self.incidents.items()):
            if now - inc["received"] > self.p.pending_timeout_ms:
                del self.incidents[iid]
                if iid not in self.done:
                    out.append(self._finalize(inc, "timeout"))
        return out


class TechMonitor:
    def __init__(self, dev: str, low_battery_v: float = 3.4, offline_after_ms: int = 120_000):
        self.dev = dev
        self.low_v = low_battery_v
        self.offline_after = offline_after_ms
        self.last_seen: int | None = None
        self.offline_since: int | None = None
        self.offline_alerted = False
        self.lowbat_armed = True

    def seen(self, now: int) -> None:
        self.last_seen = now
        self.offline_since = None
        self.offline_alerted = False

    def on_status(self, st: dict, now: int) -> list[dict]:
        out = []
        if st.get("online") is False:
            self.offline_since = self.offline_since or now
            return out
        self.seen(now)
        v = st.get("battery_v")
        if v is not None:
            if v < self.low_v and self.lowbat_armed:
                self.lowbat_armed = False
                out.append({"id": f"{self.dev}-lowbat-{now}", "dev": self.dev, "t": now, "type": "low_battery",
                            "severity": "info", "source": "device", "prob": None, "prev_label": None,
                            "cancelled": False, "notify": True, "battery_v": v})
            elif v > self.low_v + 0.2:
                self.lowbat_armed = True
        return out

    def tick(self, now: int) -> list[dict]:
        if self.last_seen is None or self.offline_alerted:
            return []
        since = self.offline_since or self.last_seen
        if now - since >= self.offline_after:
            self.offline_alerted = True
            return [{"id": f"{self.dev}-offline-{since}", "dev": self.dev, "t": since, "type": "offline",
                     "severity": "info", "source": "edge", "prob": None, "prev_label": None,
                     "cancelled": False, "notify": True}]
        return []


class SensorDecimator:
    """Gom mẫu dày (IMU 50 Hz, áp suất 10 Hz) thành một điểm mỗi `period_ms` cho biểu đồ dashboard.

    Mỗi điểm: (t giữa khoảng, trung bình x, lớn nhất x, trung bình y). Giữ cả LỚN NHẤT để đỉnh va chạm khi té
    (~20 ms, vài g) không bị trung bình làm mất. y tùy chọn (vd độ lớn con quay); không có thì None.
    Mẫu thuộc khoảng cũ hơn khoảng đang gom (gói tới trễ) bị bỏ: biểu đồ chỉ cần dữ liệu thời gian thực.
    """

    def __init__(self, period_ms: int = 200, maxlen: int = 600):
        self.period = period_ms
        self.points: deque[tuple] = deque(maxlen=maxlen)
        self._key: int | None = None
        self._n = 0
        self._sx = self._sy = 0.0
        self._mx = float("-inf")
        self._has_y = False

    def add(self, t: float, x: float, y: float | None = None) -> None:
        key = int(t // self.period)
        if self._key is not None and key < self._key:
            return
        if key != self._key:
            self._flush()
            self._key, self._n, self._sx, self._sy, self._mx, self._has_y = key, 0, 0.0, 0.0, float("-inf"), False
        self._n += 1
        self._sx += x
        self._mx = max(self._mx, x)
        if y is not None:
            self._sy += y
            self._has_y = True

    def _flush(self) -> None:
        if self._key is None or self._n == 0:
            return
        t = int(self._key * self.period + self.period // 2)
        self.points.append((t, self._sx / self._n, self._mx, self._sy / self._n if self._has_y else None))
        self._n = 0

    def since(self, t: float, limit: int = 100) -> list[tuple]:
        """Các điểm đã chốt có thời điểm > t (mới nhất `limit` điểm)."""
        out = [p for p in self.points if p[0] > t]
        return out[-limit:]

    def window(self, t_from: float) -> list[tuple]:
        return [p for p in self.points if p[0] >= t_from]
