import type { EventType, Label } from "./types";

export const LABEL_VI: Record<Label, string> = {
  stand: "Đứng",
  sit: "Ngồi",
  lie: "Nằm",
  walk: "Đi",
  run: "Chạy",
  stairs_up: "Lên cầu thang",
  stairs_down: "Xuống cầu thang",
  fall: "Té",
};

// Màu cố định cho từng hoạt động, dùng thống nhất ở mọi biểu đồ. Đỏ chỉ dành cho "Té".
export const LABEL_COLOR: Record<Label, string> = {
  stand: "#3b82f6",
  sit: "#14b8a6",
  lie: "#8b5cf6",
  walk: "#22c55e",
  run: "#f97316",
  stairs_up: "#eab308",
  stairs_down: "#a16207",
  fall: "#dc2626",
};

export const EVENT_VI: Record<EventType, string> = {
  fall: "Té ngã",
  sos: "SOS",
  low_battery: "Pin yếu",
  offline: "Mất kết nối",
};

export const SEVERITY_VI = { high: "Cao", medium: "Trung bình", info: "Thông tin" } as const;

export const SOURCE_VI: Record<string, string> = {
  both: "Ngưỡng + model",
  threshold: "Ngưỡng (ESP32)",
  model: "Model (Pi)",
  device: "Nút trên thiết bị",
  edge: "Pi",
};

export const STAGE_VI: Record<string, string> = {
  device_pi: "Thiết bị → Pi",
  infer: "Suy luận trên Pi",
  sample_result: "Mẫu cuối → kết quả",
  pi_cloud: "Pi → cloud",
};

export const labelVi = (l: string | null | undefined) => (l ? LABEL_VI[l as Label] ?? l : "—");
export const labelColor = (l: string | null | undefined) => (l ? LABEL_COLOR[l as Label] ?? "#94a3b8" : "#94a3b8");
