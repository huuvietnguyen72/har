import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ActivityBand, Card, Empty, ErrorNote, Legend, Stat } from "../components/ui";
import { useLive } from "../context";
import { dataSource } from "../data";
import { dayBounds, fmtDuration, toDayString } from "../format";
import { useAsync } from "../hooks";
import { LABEL_COLOR, LABEL_VI } from "../labels";
import { LABELS } from "../types";
import type { DaySummary, HarEvent, Segment } from "../types";

const ACTIVE = ["walk", "run", "stairs_up", "stairs_down"] as const;

export default function History() {
  const { selectedDev } = useLive();
  const [day, setDay] = useState(() => toDayString(new Date()));
  const [a, b] = dayBounds(day);
  const dev = selectedDev ?? "";

  const segs = useAsync<Segment[]>(() => (dev ? dataSource.getSegments(dev, a, b) : Promise.resolve([])), [dev, day]);
  const week = useAsync<DaySummary[]>(() => (dev ? dataSource.getSummary(dev, day, 7) : Promise.resolve([])), [dev, day]);
  const events = useAsync<HarEvent[]>(() => dataSource.getEvents(dev || undefined, 500), [dev]);

  const today = week.data?.[week.data.length - 1];
  const bars = LABELS.filter((l) => l !== "fall").map((l) => ({
    label: l, name: LABEL_VI[l], minutes: Math.round(((today?.seconds[l] ?? 0) / 60) * 10) / 10,
  }));
  const weekRows = (week.data ?? []).map((d) => {
    const row: Record<string, number | string> = { day: d.day.slice(8, 10) + "/" + d.day.slice(5, 7) };
    LABELS.forEach((l) => (row[l] = Math.round((d.seconds[l] ?? 0) / 360) / 10)); // giờ
    return row;
  });
  const activeS = today ? ACTIVE.reduce((s, l) => s + (today.seconds[l] ?? 0), 0) : 0;
  const shift = (n: number) => setDay(toDayString(new Date(a + n * 86_400_000 + 3600_000)));
  const isToday = day === toDayString(new Date());

  return (
    <div className="grid">
      <Card className="span-all" title="Lịch sử theo ngày" actions={
        <div className="day-picker">
          <button className="btn-ghost" onClick={() => shift(-1)} aria-label="Ngày trước">‹</button>
          <input type="date" value={day} max={toDayString(new Date())} onChange={(e) => e.target.value && setDay(e.target.value)} />
          <button className="btn-ghost" onClick={() => shift(1)} disabled={isToday} aria-label="Ngày sau">›</button>
        </div>
      }>
        <ErrorNote error={segs.error || week.error} />
        <div className="stats">
          <Stat label="Thời gian có dữ liệu" value={today ? fmtDuration(today.online_s) : "—"} />
          <Stat label="Vận động (đi, chạy, cầu thang)" value={today ? fmtDuration(activeS) : "—"} />
          <Stat label="Cảnh báo" value={today?.n_alerts ?? "—"} sub={today?.n_cancelled ? `${today.n_cancelled} lần đã hủy` : undefined} />
        </div>
        <h3>Dòng thời gian</h3>
        {segs.data?.length ? (
          <>
            <ActivityBand segments={segs.data} from={a} to={b} ticks={8} height={44} events={events.data ?? []} />
            <Legend labels={[...new Set(segs.data.map((s) => s.label))]} />
          </>
        ) : (
          <Empty>{segs.loading ? "Đang tải…" : "Không có dữ liệu trong ngày này."}</Empty>
        )}
      </Card>

      <Card title="Thời lượng mỗi hoạt động (phút)">
        <div className="chart">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={bars} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke="var(--grid)" />
              <XAxis type="number" stroke="var(--muted)" fontSize={12} />
              <YAxis type="category" dataKey="name" width={110} stroke="var(--muted)" fontSize={12} />
              <Tooltip formatter={(v: number) => [`${v} phút`, "Thời lượng"]} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)" }} />
              <Bar dataKey="minutes" radius={[0, 4, 4, 0]}>
                {bars.map((d) => <Cell key={d.label} fill={LABEL_COLOR[d.label]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="So sánh 7 ngày (giờ)">
        <div className="chart">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={weekRows} margin={{ right: 8 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="day" stroke="var(--muted)" fontSize={12} />
              <YAxis stroke="var(--muted)" fontSize={12} />
              <Tooltip formatter={(v: number, k: string) => [`${v} giờ`, LABEL_VI[k as keyof typeof LABEL_VI] ?? k]}
                contentStyle={{ background: "var(--card)", border: "1px solid var(--border)" }} />
              {LABELS.filter((l) => l !== "fall").map((l) => (
                <Bar key={l} dataKey={l} stackId="a" fill={LABEL_COLOR[l]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <Legend labels={LABELS.filter((l) => l !== "fall")} />
      </Card>
    </div>
  );
}
