import type { ReactNode } from "react";
import { EVENT_VI, LABEL_VI, SEVERITY_VI, labelColor } from "../labels";
import type { HarEvent, Label, Segment } from "../types";
import { fmtDateTime, fmtHM, fmtDuration } from "../format";

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "ok" | "warn" | "danger" | "neutral" | "info"; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function LabelChip({ label }: { label: string | null }) {
  if (!label) return <span className="muted">—</span>;
  return (
    <span className="chip">
      <i style={{ background: labelColor(label) }} />
      {LABEL_VI[label as Label] ?? label}
    </span>
  );
}

export function EventBadge({ e }: { e: HarEvent }) {
  if (e.cancelled) return <Badge tone="neutral">{EVENT_VI[e.type]} · đã hủy</Badge>;
  const tone = e.severity === "high" ? "danger" : e.severity === "medium" ? "warn" : "info";
  return <Badge tone={tone}>{EVENT_VI[e.type]} · {SEVERITY_VI[e.severity]}</Badge>;
}

export function Legend({ labels }: { labels: string[] }) {
  return (
    <div className="legend">
      {labels.map((l) => (
        <span key={l} className="chip">
          <i style={{ background: labelColor(l) }} />
          {LABEL_VI[l as Label] ?? l}
        </span>
      ))}
    </div>
  );
}

/** Dải màu hoạt động theo thời gian (div tuyệt đối, nhẹ hơn vẽ bằng thư viện biểu đồ). */
export function ActivityBand({ segments, from, to, ticks = 6, height = 36, events = [] }: {
  segments: Segment[]; from: number; to: number; ticks?: number; height?: number; events?: HarEvent[];
}) {
  const span = to - from;
  const pos = (t: number) => `${(Math.max(0, Math.min(1, (t - from) / span)) * 100).toFixed(3)}%`;
  const tickTimes = Array.from({ length: ticks + 1 }, (_, i) => from + (span * i) / ticks);
  return (
    <div className="band-wrap">
      <div className="band" style={{ height }} role="img" aria-label="Dải hoạt động theo thời gian">
        {segments.map((s) => {
          const a = Math.max(s.start, from);
          const b = Math.min(s.end, to);
          if (b <= a) return null;
          return (
            <div key={s.start} className="band-seg"
              style={{ left: pos(a), width: `${((b - a) / span) * 100}%`, background: labelColor(s.label) }}
              title={`${LABEL_VI[s.label]} · ${fmtHM(s.start)}–${fmtHM(s.end)} · ${fmtDuration((s.end - s.start) / 1000)}`} />
          );
        })}
        {events.filter((e) => e.t >= from && e.t <= to && (e.type === "fall" || e.type === "sos")).map((e) => (
          <div key={e.id} className={`band-mark ${e.cancelled ? "cancelled" : ""}`} style={{ left: pos(e.t) }}
            title={`${EVENT_VI[e.type]} ${fmtDateTime(e.t)}${e.cancelled ? " (đã hủy)" : ""}`} />
        ))}
      </div>
      <div className="band-ticks">
        {tickTimes.map((t, i) => (
          <span key={i} style={{ left: `${(i / ticks) * 100}%` }}>{fmtHM(t)}</span>
        ))}
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="error">Không tải được dữ liệu: {String((error as Error).message ?? error)}</div>;
}
