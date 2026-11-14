// mockDataSource: dữ liệu MẪU sinh trong trình duyệt để làm giao diện trước khi có API.
// Mọi số liệu ở đây là bịa, không dùng cho báo cáo.
import { LABELS } from "../types";
import type {
  DataSource, DaySummary, Experiment, HarEvent, Label, LiveHandlers, MetricsResponse, Segment, Status, StatusLogRow,
} from "../types";
import { dayBounds } from "../format";

const DEV = "har01";
const MIN = 60_000;

function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

function pick<T>(r: () => number, items: [T, number][]): T {
  const total = items.reduce((s, [, w]) => s + w, 0);
  let x = r() * total;
  for (const [v, w] of items) if ((x -= w) <= 0) return v;
  return items[0][0];
}

function buildSegments(): Segment[] {
  const r = rng(42);
  const now = Date.now();
  const start = new Date(now - 7 * 86_400_000);
  start.setHours(0, 0, 0, 0);
  const segs: Segment[] = [];
  let t = start.getTime();
  while (t < now) {
    const h = new Date(t).getHours();
    let label: Label;
    let dur: number;
    if (h >= 22 || h < 6) {
      label = "lie";
      dur = (20 + r() * 60) * MIN;
    } else {
      label = pick<Label>(r, [["sit", 5], ["stand", 3], ["walk", 3], ["lie", 1], ["stairs_up", 0.4], ["stairs_down", 0.4], ["run", 0.15]]);
      dur = (label.startsWith("stairs") ? 0.5 + r() : label === "run" ? 3 + r() * 8 : 2 + r() * 25) * MIN;
    }
    const end = Math.min(t + dur, now);
    segs.push({ dev: DEV, start: t, end, label, conf_avg: 0.75 + r() * 0.22 });
    t = end;
  }
  return segs;
}

const segments = buildSegments();
const now0 = Date.now();
const events: HarEvent[] = [
  ev("har01-m1", now0 - 26 * 3600_000, "fall", "high", "both", 0.93, "walk", { acknowledged: true, acknowledged_by: "demo@har.vn" }),
  ev("har01-m2", now0 - 5 * 3600_000, "fall", "info", "threshold", 0.12, "sit", { cancelled: true }),
  ev("har01-m3", now0 - 3 * 3600_000, "low_battery", "info", "device", null, null),
  ev("har01-m4", now0 - 50 * 3600_000, "sos", "high", "device", null, "stand", { acknowledged: true, delivered_late: true }),
];

function ev(id: string, t: number, type: HarEvent["type"], severity: HarEvent["severity"], source: HarEvent["source"],
  prob: number | null, prev: string | null, extra: Partial<HarEvent> = {}): HarEvent {
  return { id, dev: DEV, t, type, severity, source, prob, prev_label: prev, battery_pct: 64, cancelled: false,
    acknowledged: false, acknowledged_at: null, acknowledged_by: null, delivered_late: false, received_at: t + 800, ...extra };
}

let status: Status = {
  dev: DEV, t: Date.now(), label: segments[segments.length - 1].label, conf: 0.88, online: true, battery_v: 3.86,
  battery_pct: 58, temp_c: 29.3, rh: 71, rssi: -57, model: "rf-imu+baro-2.5s-v1 (mẫu)", received_at: Date.now() + 300,
  alias: "Người đeo 1 (dữ liệu mẫu)", fw: "0.3.0",
};

function confusion(labels: string[], acc: number, seed: number) {
  const r = rng(seed);
  return labels.map((_, i) => labels.map((__, j) => {
    const n = 120 + Math.round(r() * 40);
    if (i === j) return Math.round(n * acc);
    const near = (labels[i].startsWith("stairs") && (labels[j] === "walk" || labels[j].startsWith("stairs"))) ||
      (labels[i] === "walk" && labels[j].startsWith("stairs"));
    return Math.round(r() * (near ? n * (1 - acc) : 3));
  }));
}

function exp(id: string, model: string, features: string, window_s: number, acc: number, f1: number,
  stairs: number, seed: number): Experiment {
  const labels = [...LABELS];
  const r = rng(seed);
  const per: Record<string, number> = {};
  labels.forEach((l) => (per[l] = l.startsWith("stairs") ? stairs + r() * 0.04 : Math.min(0.99, f1 + 0.06 * (r() - 0.3))));
  return { experiment: id, model, features, window_s, accuracy: acc, macro_f1: f1, f1_per_class: per,
    confusion: { labels, matrix: confusion(labels, acc, seed) }, n_windows: 9800, n_subjects: 6,
    extra: { mock: true, cv: "GroupKFold k=5 theo người", infer_ms_train_machine: id.startsWith("B") ? 3.1 : 1.4 },
    created_at: new Date().toISOString() };
}

const metrics: MetricsResponse = {
  experiments: [
    exp("A1", "rf-imu-2.5s-v1", "imu", 2.5, 0.86, 0.82, 0.62, 1),
    exp("A2", "rf-imu+baro-2.5s-v1", "imu+baro", 2.5, 0.91, 0.89, 0.84, 2),
    exp("B1", "cnn-imu-2.5s-v1", "imu", 2.5, 0.88, 0.85, 0.66, 3),
    exp("B2", "cnn-imu+baro-2.5s-v1", "imu+baro", 2.5, 0.92, 0.9, 0.86, 4),
    exp("C", "rf-imu+baro-2s-v1", "imu+baro", 2.0, 0.9, 0.87, 0.8, 5),
    { experiment: "D", model: "threshold vs rf vs fusion", features: "imu+baro", window_s: 2.5, accuracy: null,
      macro_f1: null, f1_per_class: null, confusion: null, n_windows: null, n_subjects: 6, created_at: new Date().toISOString(),
      extra: { mock: true, adl_hours: 2.4, methods: {
        threshold: { sensitivity: 0.93, false_alarms_per_hour: 0.83, specificity_recordings: 0.9, detect_delay_ms_median: 2000 },
        model: { sensitivity: 0.87, false_alarms_per_hour: 0.42, specificity_recordings: 0.95, detect_delay_ms_median: 6000 },
        combined: { sensitivity: 0.97, false_alarms_per_hour: 0.42, specificity_recordings: 0.95, detect_delay_ms_median: 2000 },
      } } },
  ],
  system: [{ dev: DEV, day: new Date().toISOString().slice(0, 10), packet_loss: 0.0031, packets: 152000, battery_hours: 16.5,
    latency: { device_pi: { median: 42, p95: 95 }, infer: { median: 6.2, p95: 9.8 }, sample_result: { median: 61, p95: 140 },
      pi_cloud: { median: 180, p95: 640 } }, extra: { mock: true } }],
  running_models: { [DEV]: status.model },
};

const delay = <T,>(v: T, ms = 150) => new Promise<T>((res) => setTimeout(() => res(structuredClone(v)), ms));

function summarize(day: string): DaySummary {
  const [a, b] = dayBounds(day);
  const seconds = Object.fromEntries(LABELS.map((l) => [l, 0])) as Record<Label, number>;
  let online = 0;
  for (const s of segments) {
    const d = (Math.min(s.end, b) - Math.max(s.start, a)) / 1000;
    if (d > 0) {
      seconds[s.label] += d;
      online += d;
    }
  }
  const evs = events.filter((e) => e.t >= a && e.t < b);
  return { dev: DEV, day, seconds, online_s: online, n_alerts: evs.filter((e) => !e.cancelled && (e.type === "fall" || e.type === "sos")).length,
    n_cancelled: evs.filter((e) => e.cancelled).length };
}

export const mockDataSource: DataSource = {
  kind: "mock",
  async login(email, password) {
    if (!email || password.length < 3) throw new Error("Nhập email và mật khẩu bất kỳ (≥ 3 ký tự) để xem bản mẫu");
    return delay({ token: "mock", expiresAt: Date.now() + 12 * 3600_000, user: { email, role: "viewer" } });
  },
  getStatus: () => delay([status]),
  getStatusHistory: (_dev, from, to) => {
    const rows: StatusLogRow[] = [];
    for (let t = from; t < to; t += 10 * MIN) {
      const h = (t - from) / 3600_000;
      rows.push({ dev: DEV, t, online: true, battery_v: 4.15 - h * 0.03, battery_pct: Math.max(0, 98 - h * 5), temp_c: 29, rh: 70 });
    }
    return delay(rows);
  },
  getSegments: (_dev, from, to) => delay(segments.filter((s) => s.end > from && s.start < to)),
  getSummary: (_dev, day, days = 1) => {
    const [a] = dayBounds(day);
    const out = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(a - i * 86_400_000);
      out.push(summarize(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`));
    }
    return delay(out);
  },
  getEvents: () => delay([...events].sort((x, y) => y.t - x.t)),
  ackEvent: async (id, acknowledged = true) => {
    const e = events.find((x) => x.id === id)!;
    e.acknowledged = acknowledged;
    e.acknowledged_at = acknowledged ? new Date().toISOString() : null;
    e.acknowledged_by = acknowledged ? "bạn (mẫu)" : null;
    return delay(e);
  },
  getMetrics: () => delay(metrics),
  subscribe(h: LiveHandlers) {
    h.onConnection?.("ws");
    const r = rng(Date.now() % 1000);
    const timer = window.setInterval(() => {
      const last = segments[segments.length - 1];
      const now = Date.now();
      if (r() < 0.15) {
        last.end = now;
        const label = pick<Label>(r, [["sit", 3], ["stand", 3], ["walk", 3], ["lie", 1], ["stairs_up", 0.5]]);
        segments.push({ dev: DEV, start: now, end: now, label, conf_avg: 0.85 });
      } else last.end = now;
      const cur = segments[segments.length - 1];
      status = { ...status, t: now, received_at: now + 250, label: cur.label, conf: 0.7 + r() * 0.29 };
      h.onStatus?.(structuredClone(status));
    }, 5000);
    // Một cảnh báo té mẫu sau 40 s để xem thông báo tức thời
    const evTimer = window.setTimeout(() => {
      const e = ev(`har01-demo-${Date.now()}`, Date.now() - 1500, "fall", "high", "both", 0.91, status.label);
      events.push(e);
      h.onEvent?.({ ...e, new: true });
    }, 40_000);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(evTimer);
    };
  },
};
