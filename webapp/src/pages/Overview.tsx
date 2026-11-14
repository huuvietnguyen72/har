import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ActivityBand, Badge, Card, Empty, ErrorNote, EventBadge, LabelChip, Legend, Stat } from "../components/ui";
import { useLive, useNow } from "../context";
import { dataSource } from "../data";
import { fmtAgo, fmtDateTime, fmtNum } from "../format";
import { useAsync } from "../hooks";
import { LABEL_VI, SOURCE_VI, labelColor } from "../labels";
import type { HarEvent, Label, Segment } from "../types";

const HOUR = 3600_000;

export default function Overview() {
  const { statuses, selectedDev, setSelectedDev, lastEvent } = useLive();
  const now = useNow(1000);
  const devs = Object.keys(statuses).sort();
  const st = selectedDev ? statuses[selectedDev] : undefined;
  const [range, setRange] = useState(() => ({ to: Date.now() }));

  // tải lại dải hoạt động mỗi 30 s và mỗi khi nhãn đổi
  useEffect(() => {
    const t = window.setInterval(() => setRange({ to: Date.now() }), 30_000);
    return () => window.clearInterval(t);
  }, []);
  useEffect(() => setRange({ to: Date.now() }), [st?.label]);

  const segs = useAsync<Segment[]>(
    () => (selectedDev ? dataSource.getSegments(selectedDev, range.to - HOUR, range.to) : Promise.resolve([])),
    [selectedDev, range.to],
  );
  const events = useAsync<HarEvent[]>(() => dataSource.getEvents(selectedDev ?? undefined, 5), [selectedDev, lastEvent?.id]);

  // Nối đoạn đang diễn ra (chưa đóng nên chưa lên cloud) từ trạng thái hiện tại
  const bandSegments = useMemo(() => {
    const list = [...(segs.data ?? [])];
    if (st?.online && st.label) {
      const lastEnd = list.length ? list[list.length - 1].end : range.to - HOUR;
      list.push({ dev: st.dev, start: lastEnd, end: now, label: st.label, conf_avg: st.conf });
    }
    return list;
  }, [segs.data, st, now, range.to]);

  if (!devs.length) {
    return (
      <Card title="Tổng quan">
        <Empty>Chưa có thiết bị nào gửi dữ liệu. Kiểm tra Pi (har-uplink) và API key thiết bị.</Empty>
      </Card>
    );
  }

  const latency = st ? st.received_at - st.t : null;
  const label = st?.online ? st.label : null;
  const unhandled = (events.data ?? []).filter((e) => !e.acknowledged && !e.cancelled && (e.type === "fall" || e.type === "sos"));

  return (
    <div className="grid">
      {devs.length > 1 && (
        <div className="span-all dev-switch">
          {devs.map((d) => (
            <button key={d} className={d === selectedDev ? "pill active" : "pill"} onClick={() => setSelectedDev(d)}>
              {statuses[d].alias || d}
            </button>
          ))}
        </div>
      )}

      {unhandled.length > 0 && (
        <Link to="/alerts" className="span-all alert-banner">
          🚨 {unhandled.length} cảnh báo chưa xử lý — mới nhất lúc {fmtDateTime(unhandled[0].t)}. Bấm để xem.
        </Link>
      )}

      <Card className="hero" title={<>Hoạt động hiện tại <span className="muted">· {st?.alias || st?.dev}</span></>}
        actions={st?.online ? <Badge tone="ok">Online</Badge> : <Badge tone="danger">Offline</Badge>}>
        <div className="hero-body" style={{ ["--c" as string]: labelColor(label) }}>
          <div className="hero-label">{label ? LABEL_VI[label as Label] : st?.online ? "Đang chờ…" : "Không có dữ liệu"}</div>
          <div className="hero-conf">
            {st?.online && st.conf != null && (
              <>
                <div className="meter"><span style={{ width: `${Math.round(st.conf * 100)}%` }} /></div>
                <span>Độ tin cậy {Math.round(st.conf * 100)}%</span>
              </>
            )}
          </div>
          <div className="muted small">
            Cập nhật {st ? fmtAgo(st.t, now) : "—"}
            {latency != null && latency >= 0 && ` · trễ Pi→cloud ${latency} ms`}
            {st?.model && ` · model ${st.model}`}
          </div>
        </div>
      </Card>

      <Card title="Thiết bị">
        <div className="stats">
          <Stat label="Pin" value={st?.battery_pct != null ? `${Math.round(st.battery_pct)}%` : "—"}
            sub={st?.battery_v != null ? `${fmtNum(st.battery_v)} V` : undefined} />
          <Stat label="Nhiệt độ" value={st?.temp_c != null ? `${fmtNum(st.temp_c, 1)} °C` : "—"} />
          <Stat label="Độ ẩm" value={st?.rh != null ? `${Math.round(st.rh)}%` : "—"} />
          <Stat label="Wi-Fi" value={st?.rssi != null ? `${st.rssi} dBm` : "—"} sub={st?.fw ? `firmware ${st.fw}` : undefined} />
        </div>
        {st?.battery_pct != null && st.battery_pct < 20 && <div className="warn-note">Pin yếu — sạc bộ đeo.</div>}
      </Card>

      <Card className="span-all" title="1 giờ qua" actions={<Link to="/history" className="link">Xem lịch sử →</Link>}>
        <ErrorNote error={segs.error} />
        <ActivityBand segments={bandSegments} from={range.to - HOUR} to={Math.max(now, range.to)} events={events.data ?? []} />
        <Legend labels={[...new Set(bandSegments.map((s) => s.label))]} />
      </Card>

      <Card className="span-all" title="Cảnh báo gần nhất" actions={<Link to="/alerts" className="link">Tất cả →</Link>}>
        <ErrorNote error={events.error} />
        {events.data?.length ? (
          <ul className="event-list">
            {events.data.slice(0, 3).map((e) => (
              <li key={e.id}>
                <EventBadge e={e} />
                <span>{fmtDateTime(e.t)}</span>
                <span className="muted">{e.source ? SOURCE_VI[e.source] : ""}</span>
                {e.prev_label && <span className="muted">trước đó: <LabelChip label={e.prev_label} /></span>}
                {e.acknowledged ? <Badge tone="ok">Đã xử lý</Badge> : !e.cancelled && <Badge tone="warn">Chưa xử lý</Badge>}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>Chưa có cảnh báo.</Empty>
        )}
      </Card>
    </div>
  );
}
