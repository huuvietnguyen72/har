import { useEffect, useState } from "react";
import { Badge, Card, Empty, ErrorNote, EventBadge, LabelChip } from "../components/ui";
import { useLive } from "../context";
import { dataSource } from "../data";
import { fmtDateTime, fmtPct } from "../format";
import { useAsync } from "../hooks";
import { SOURCE_VI } from "../labels";
import type { HarEvent } from "../types";

type Filter = "open" | "all" | "fall";

export default function Alerts() {
  const { lastEvent } = useLive();
  const { data, error, loading, setData } = useAsync<HarEvent[]>(() => dataSource.getEvents(undefined, 300), []);
  const [filter, setFilter] = useState<Filter>("open");
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);

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
    } finally {
      setBusy(null);
    }
  };

  const rows = (data ?? []).filter((e) =>
    filter === "all" ? true : filter === "fall" ? e.type === "fall" || e.type === "sos" : !e.acknowledged && !e.cancelled);
  const openCount = (data ?? []).filter((e) => !e.acknowledged && !e.cancelled).length;

  return (
    <Card title="Cảnh báo" actions={
      <div className="segmented">
        {([["open", `Chưa xử lý (${openCount})`], ["fall", "Té & SOS"], ["all", "Tất cả"]] as [Filter, string][]).map(([k, t]) => (
          <button key={k} className={filter === k ? "active" : ""} onClick={() => setFilter(k)}>{t}</button>
        ))}
      </div>
    }>
      <ErrorNote error={error} />
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
                <tr key={e.id} className={fresh.has(e.id) ? "fresh" : ""}>
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
                      ? <span title={e.acknowledged_at ?? ""}><Badge tone="ok">Đã xử lý</Badge> <span className="small muted">{e.acknowledged_by}</span></span>
                      : <Badge tone="warn">Chưa xử lý</Badge>}
                  </td>
                  <td>
                    {!e.cancelled && (
                      <button className={e.acknowledged ? "btn-ghost small" : "btn small"} disabled={busy === e.id}
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
      <p className="muted small">Cảnh báo té/SOS cũng được gửi tới nhóm Telegram "Người thân". Cảnh báo đã hủy bằng nút trên thiết bị chỉ được ghi lại.</p>
    </Card>
  );
}
