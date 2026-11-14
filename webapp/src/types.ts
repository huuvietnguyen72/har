// Kiểu dữ liệu khớp với backend (docs/api.md, docs/data-schema.md)

export const LABELS = ["stand", "sit", "lie", "walk", "run", "stairs_up", "stairs_down", "fall"] as const;
export type Label = (typeof LABELS)[number];

export interface Status {
  dev: string;
  t: number;
  label: Label | null;
  conf: number | null;
  online: boolean;
  battery_v: number | null;
  battery_pct: number | null;
  temp_c: number | null;
  rh: number | null;
  rssi: number | null;
  model: string | null;
  received_at: number;
  alias?: string | null;
  fw?: string | null;
}

export interface Segment {
  dev: string;
  start: number;
  end: number;
  label: Label;
  conf_avg: number | null;
}

export interface DaySummary {
  dev: string;
  day: string; // YYYY-MM-DD
  seconds: Record<Label, number>;
  online_s: number;
  n_alerts: number;
  n_cancelled: number;
}

export type EventType = "fall" | "sos" | "low_battery" | "offline";

export interface HarEvent {
  id: string;
  dev: string;
  t: number;
  type: EventType;
  severity: "high" | "medium" | "info";
  source: "threshold" | "model" | "both" | "device" | "edge" | null;
  prob: number | null;
  prev_label: string | null;
  battery_pct: number | null;
  cancelled: boolean;
  acknowledged: boolean;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  delivered_late: boolean;
  received_at: number;
  new?: boolean;
}

export interface Experiment {
  experiment: string;
  model: string;
  features: string | null;
  window_s: number | null;
  accuracy: number | null;
  macro_f1: number | null;
  f1_per_class: Record<string, number> | null;
  confusion: { labels: string[]; matrix: number[][] } | null;
  n_windows: number | null;
  n_subjects: number | null;
  extra: Record<string, any> | null;
  created_at: string;
}

export interface SystemMetric {
  dev: string;
  day: string;
  latency: Record<string, { median: number; p95: number; n?: number }> | null;
  packet_loss: number | null;
  packets: number | null;
  battery_hours: number | null;
  extra: Record<string, any> | null;
}

export interface MetricsResponse {
  experiments: Experiment[];
  system: SystemMetric[];
  running_models: Record<string, string | null>;
}

export interface StatusLogRow {
  dev: string;
  t: number;
  online: boolean;
  battery_v: number | null;
  battery_pct: number | null;
  temp_c: number | null;
  rh: number | null;
}

export interface Session {
  token: string;
  expiresAt: number;
  user: { email: string; role: string };
}

export interface LiveHandlers {
  onStatus?: (s: Status) => void;
  onEvent?: (e: HarEvent) => void;
  onConnection?: (mode: "ws" | "polling" | "offline") => void;
}

export interface DataSource {
  kind: "api" | "mock";
  login(email: string, password: string): Promise<Session>;
  getStatus(): Promise<Status[]>;
  getStatusHistory(dev: string, from: number, to: number): Promise<StatusLogRow[]>;
  getSegments(dev: string, from: number, to: number): Promise<Segment[]>;
  getSummary(dev: string, day: string, days?: number): Promise<DaySummary[]>;
  getEvents(dev?: string, limit?: number): Promise<HarEvent[]>;
  ackEvent(id: string, acknowledged?: boolean): Promise<HarEvent>;
  getMetrics(): Promise<MetricsResponse>;
  /** Đăng ký nhận trạng thái và cảnh báo mới (WebSocket, tự chuyển sang hỏi lại mỗi 10 s nếu rớt). */
  subscribe(handlers: LiveHandlers): () => void;
}
