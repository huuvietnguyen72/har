import { useEffect, useRef, useState } from "react";
import { Badge, Card, Empty, ErrorNote, EventBadge, LabelChip } from "../components/ui";
import { useLive } from "../context";
import { dataSource } from "../data";
import { fmtDateTime, fmtPct, fmtTime } from "../format";
import { useAsync } from "../hooks";
import { SOURCE_VI } from "../labels";
import type { HarEvent } from "../types";

type Filter = "open" | "all" | "fall";

// "Chưa xử lý" chỉ gồm té và SOS: mất kết nối, pin yếu là thông tin kỹ thuật, xem ở tab Tất cả
const isAlarm = (e: HarEvent) => e.type === "fall" || e.type === "sos";
const isOpen = (e: HarEvent) => isAlarm(e) && !e.acknowledged && !e.cancelled;
// dòng vừa bấm Đã xử lý ở lại tại chỗ một lúc (không để dòng khác trượt lên chỗ đó gây nhầm)
const KEEP_ACKED_MS = 3000;

export default function Alerts() {
  const { lastEvent } = useLive();
  const { data, error, loading, setData } = useAsync<HarEvent[]>(() => dataSource.getEvents(undefined, 300), []);
  const [filter, setFilter] = useState<Filter>("open");
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [bulk, setBulk] = useState<{ done: number; total: number } | null>(null);
  const [justAcked, setJustAcked] = useState<Set<string>>(new Set());
  const timers = useRef<number[]>([]);
  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  const keepVisible = (id: string) => {
    setJustAcked((s) => new Set(s).add(id));
    timers.current.push(window.setTimeout(() => setJustAcked((s) => {
      const n = new Set(s);
      n.delete(id);
      return n;
    }), KEEP_ACKED_MS));
  };

  // Sự kiện mới qua WebSocket: chèn/cập nhật ngay, tô sáng vài giây
  useEffect(() => {
    if (!lastEvent) return;
    setData((prev) => {
      const list = (prev ?? []).filter((e) => e.id !== lastEvent.id);
      return [lastEvent, ...list].sort((x, y) => y.t - x.t);
    });
    if (lastEvent.new) {
      setFresh((s) => new Set(s).add(lastEvent.id));
      const t = window.setTimeout(() => setFresh((s) => {
        const n = new Set(s);
        n.delete(lastEvent.id);
        return n;
      }), 8000);
      return () => window.clearTimeout(t);
    }
  }, [lastEvent, setData]);

  const ack = async (e: HarEvent, value: boolean) => {
    setBusy(e.id);
    try {
      const upd = await dataSource.ackEvent(e.id, value);
      setData((prev) => (prev ?? []).map((x) => (x.id === upd.id ? upd : x)));
      if (value) keepVisible(upd.id);
    } finally {
      setBusy(null);
    }
  };

  const open = (data ?? []).filter(isOpen);
  const ackAll = async () => {
    if (!open.length || !window.confirm(`Đánh dấu ${open.length} cảnh báo té/SOS chưa xử lý là "Đã xử lý"?`)) return;
    setBulk({ done: 0, total: open.length });
    try {
      for (const [i, e] of open.entries()) {
        const upd = await dataSource.ackEvent(e.id, true);
        setData((prev) => (prev ?? []).map((x) => (x.id === upd.id ? upd : x)));
        keepVisible(upd.id);
        setBulk({ done: i + 1, total: open.length });
      }
    } finally {
      setBulk(null);
    }
  };

  const rows = (data ?? []).filter((e) =>
    filter === "all" ? true : filter === "fall" ? isAlarm(e) : isOpen(e) || justAcked.has(e.id));
  const openCount = open.length;

  return (
    <Card title="Cảnh báo" actions={
      <div className="segmented">
        {([["open", `Chưa xử lý (${openCount})`], ["fall", "Té & SOS"], ["all", "Tất cả"]] as [Filter, string][]).map(([k, t]) => (
          <button key={k} className={filter === k ? "active" : ""} onClick={() => setFilter(k)}>{t}</button>
        ))}
      </div>
    }>
      <ErrorNote error={error} />
      {filter === "open" && (
        <div className="alerts-toolbar">
          <span className="muted small">Chỉ gồm té và SOS. Mất kết nối, pin yếu xem ở tab Tất cả.</span>
          {openCount > 0 && (
            <button className="btn-ghost small" onClick={ackAll} disabled={!!bulk}>
              {bulk ? `Đang đánh dấu ${bulk.done}/${bulk.total}…` : `Đánh dấu tất cả đã xử lý (${openCount})`}
            </button>
          )}
        </div>
      )}
      {loading && !data ? <Empty>Đang tải…</Empty> : rows.length === 0 ? <Empty>Không có cảnh báo nào.</Empty> : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Giờ</th><th>Loại · mức</th><th>Nguồn</th><th>P(té)</th><th>Trước đó</th><th>Thiết bị</th><th>Trạng thái</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className={justAcked.has(e.id) && filter === "open" ? "row-acked" : fresh.has(e.id) ? "fresh" : ""}>
                  <td data-th="Giờ">
                    {fmtDateTime(e.t)}
                    {e.delivered_late && <div className="small muted">gửi trễ</div>}
                  </td>
                  <td data-th="Loại"><EventBadge e={e} /></td>
                  <td data-th="Nguồn">{e.source ? SOURCE_VI[e.source] ?? e.source : "—"}</td>
                  <td data-th="P(té)">{fmtPct(e.prob)}</td>
                  <td data-th="Trước đó"><LabelChip label={e.prev_label} /></td>
                  <td data-th="Thiết bị">{e.dev}{e.battery_pct != null && <span className="muted"> · pin {Math.round(e.battery_pct)}%</span>}</td>
                  <td data-th="Trạng thái">
                    {e.cancelled ? <Badge>Người đeo đã hủy</Badge> : e.acknowledged
                      ? <span title={e.acknowledged_at ?? ""}><Badge tone="ok">✓ Đã xử lý</Badge> <span className="small muted">{e.acknowledged_by}</span></span>
                      : <Badge tone="warn">Chưa xử lý</Badge>}
                    {!e.cancelled && e.wearer_ack_at != null && (
                      <div className="small muted">✋ Người đeo bấm nút {fmtTime(e.wearer_ack_at)}</div>
                    )}
                  </td>
                  <td>
                    {!e.cancelled && (
                      <button className={e.acknowledged ? "btn-ghost small" : "btn small"} disabled={busy === e.id || !!bulk}
                        onClick={() => ack(e, !e.acknowledged)}>
                        {e.acknowledged ? "Bỏ đánh dấu" : "Đã xử lý"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">Cảnh báo té/SOS cũng được gửi Telegram cho từng người nhận. Người đeo hủy trong 10 s chờ: chỉ ghi lại. Người đeo bấm nút sau khi té đã xác nhận: chỉ tắt còi, cảnh báo vẫn chờ người thân xử lý.</p>
    </Card>
  );
}
