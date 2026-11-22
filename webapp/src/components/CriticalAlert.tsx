// Hộp cảnh báo té / SOS nổi giữa màn hình, ở mọi trang. Hiện khi có cảnh báo mới chưa xử lý,
// hoặc khi mở dashboard mà còn cảnh báo chưa xử lý trong 30 phút gần nhất.
// Kêu "bíp" lặp lại (Web Audio) và rung trên điện thoại cho tới khi bấm Đã xử lý / Đóng.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLive, useNow } from "../context";
import { fmtTime } from "../format";
import { LABEL_VI, SOURCE_VI } from "../labels";
import type { Label } from "../types";

function useAlarmSound(on: boolean, muted: boolean) {
  const ctxRef = useRef<AudioContext | null>(null);
  useEffect(() => {
    if (!on || muted) return;
    let stopped = false;
    const beep = () => {
      try {
        const ctx = (ctxRef.current ??= new AudioContext());
        if (ctx.state === "suspended") void ctx.resume();
        for (const [at, f] of [[0, 880], [0.25, 660]] as const) {
          const o = ctx.createOscillator();
          const g = ctx.createGain();
          o.frequency.value = f;
          g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
          g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + at + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.22);
          o.connect(g).connect(ctx.destination);
          o.start(ctx.currentTime + at);
          o.stop(ctx.currentTime + at + 0.24);
        }
        navigator.vibrate?.([300, 150, 300]);
      } catch {
        /* trình duyệt chặn âm thanh khi chưa có thao tác: vẫn hiện hộp */
      }
    };
    beep();
    const t = window.setInterval(() => !stopped && beep(), 1500);
    const limit = window.setTimeout(() => window.clearInterval(t), 60_000); // kêu tối đa 1 phút
    return () => {
      stopped = true;
      window.clearInterval(t);
      window.clearTimeout(limit);
    };
  }, [on, muted]);
}

export function CriticalAlert() {
  const { critical, ackCritical, closeCritical, statuses } = useLive();
  const [muted, setMuted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const nav = useNavigate();
  const now = useNow(1000);
  useAlarmSound(!!critical, muted);
  useEffect(() => {
    setMuted(false);
    setErr(null);
  }, [critical?.id]);
  if (!critical) return null;

  const e = critical;
  const isFall = e.type === "fall";
  const ago = Math.max(0, Math.round((now - e.t) / 1000));
  const agoText = ago < 60 ? `${ago} giây trước` : `${Math.round(ago / 60)} phút trước`;
  const who = statuses[e.dev]?.alias || e.dev;
  const ack = async () => {
    setBusy(true);
    setErr(null);
    try {
      await ackCritical();
    } catch {
      setErr("Không gửi được lên cloud, thử lại.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="critical-backdrop" role="alertdialog" aria-modal="true" aria-labelledby="critical-title">
      <div className={`critical-card ${isFall ? "critical-fall" : "critical-sos"}`}>
        <div className="critical-icon" aria-hidden>{isFall ? "🚨" : "🆘"}</div>
        <h2 id="critical-title">{isFall ? "PHÁT HIỆN TÉ NGÃ" : "GỌI TRỢ GIÚP (SOS)"}</h2>
        <p className="critical-who">{who}</p>
        <p className="critical-time">
          {fmtTime(e.t)} · <strong>{agoText}</strong>
        </p>
        <ul className="critical-facts">
          {e.source && <li>Nguồn: {SOURCE_VI[e.source] ?? e.source}</li>}
          {e.prob != null && <li>Xác suất té (model): {Math.round(e.prob * 100)}%</li>}
          {e.prev_label && <li>Hoạt động trước đó: {LABEL_VI[e.prev_label as Label] ?? e.prev_label}</li>}
          {e.severity === "high" && <li>Mức: cao</li>}
        </ul>
        {e.wearer_ack_at != null && (
          <p className="critical-wearer">
            ✋ Người đeo đã bấm nút tắt còi lúc <strong>{fmtTime(e.wearer_ack_at)}</strong>: còn phản hồi.
          </p>
        )}
        <p className="critical-hint">
          {e.wearer_ack_at != null ? "Vẫn cần gọi hoặc đến kiểm tra trước khi bấm Đã xử lý." : "Hãy liên lạc ngay với người đeo hoặc đến kiểm tra."}
        </p>
        {err && <p className="critical-err">{err}</p>}
        <div className="critical-actions">
          <button className="btn critical-ack" onClick={ack} disabled={busy} autoFocus>
            {busy ? "Đang lưu…" : "✅ Đã xử lý"}
          </button>
          <button className="btn-ghost" onClick={() => { closeCritical(); nav("/alerts"); }}>Xem chi tiết</button>
          <button className="btn-ghost" onClick={() => setMuted(true)} disabled={muted}>{muted ? "Đã tắt âm" : "🔇 Tắt âm"}</button>
          <button className="btn-ghost" onClick={closeCritical} title="Đóng hộp, cảnh báo vẫn ở trạng thái chưa xử lý">Đóng</button>
        </div>
      </div>
    </div>
  );
}
