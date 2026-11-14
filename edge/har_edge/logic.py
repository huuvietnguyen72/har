"""Logic thuần (không MQTT, không I/O) của har-infer — có unit test.

- Smoother   : đa số 3 dự đoán gần nhất, nhãn té không làm mượt
- Segmenter  : gộp dự đoán thành đoạn hoạt động (start, end, label, conf_avg)
- FallFusion : hợp nhất cảnh báo té giữa ngưỡng trên ESP32 và model trên Pi
- TechMonitor: cảnh báo kỹ thuật (pin yếu, mất kết nối)

Mọi hàm nhận thời gian qua tham số (epoch ms) để test được.
"""
from collections import Counter, deque
from dataclasses import dataclass, field


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
    p_model_only: float = 0.8  # model tự báo khi ESP32 không kích hoạt
    lie_after_s: float = 5.0  # ... và sau đó nằm ít nhất ngần này giây
    window_ms: int = 3000  # ±3 s quanh va chạm
    pending_timeout_ms: int = 15000  # suspected mà không thấy confirmed/cancelled -> coi như confirmed


class FallFusion:
    def __init__(self, dev: str, params: FusionParams | None = None):
        self.dev = dev
        self.p = params or FusionParams()
        self.preds: deque[tuple[int, float, str]] = deque(maxlen=120)  # (t, p_fall, label)
        self.incidents: dict[str, dict] = {}
        self.done: set[str] = set()
        self.candidate: dict | None = None

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
        p = self._p_fall_near(inc["t"])
        high = p is not None and p >= self.p.p_confirm
        a = self._alert(inc["id"], inc["t"], "fall", "high" if high else "medium", "both" if high else "threshold", p)
        a["peak_g"] = inc.get("peak_g")
        a["reason"] = reason
        return a

    # ---------- đầu vào ----------
    def on_device_event(self, ev: dict, now: int) -> list[dict]:
        typ = ev.get("type")
        out: list[dict] = []
        if typ == "sos":
            if ev["id"] not in self.done:
                out.append(self._alert(ev["id"], ev["t"], "sos", "high", "device", None))
        elif typ == "suspected":
            if ev["id"] not in self.done and ev["id"] not in self.incidents:
                self.incidents[ev["id"]] = {"id": ev["id"], "t": ev["t"], "peak_g": ev.get("peak_g"), "received": now}
            if self.candidate and abs(self.candidate["t"] - ev["t"]) <= 5000:
                self.candidate = None  # model và ngưỡng cùng thấy -> để incident xử lý
        elif typ in ("cancelled", "confirmed"):
            ref = ev.get("ref") or ev["id"]
            inc = self.incidents.pop(ref, None) or {"id": ref, "t": ev.get("t_impact", ev["t"]), "peak_g": ev.get("peak_g")}
            if ref in self.done:
                return out
            if typ == "cancelled":
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
        if self.candidate is None and p_fall >= self.p.p_model_only and not near_incident:
            self.candidate = {"t": t, "p": p_fall, "lie_start": None}
        elif self.candidate is not None:
            c = self.candidate
            c["p"] = max(c["p"], p_fall) if t - c["t"] <= self.p.window_ms else c["p"]
            if label == "lie":
                c["lie_start"] = c["lie_start"] or t
                if t - c["lie_start"] >= self.p.lie_after_s * 1000:
                    aid = f"{self.dev}-m{c['t']}"
                    self.candidate = None
                    if aid not in self.done:
                        out.append(self._alert(aid, c["t"], "fall", "medium", "model", c["p"]))
            elif label != "fall":
                c["lie_start"] = None
            if self.candidate is not None and t - c["t"] > 15000:
                self.candidate = None
        return out

    def tick(self, now: int) -> list[dict]:
        out = []
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
