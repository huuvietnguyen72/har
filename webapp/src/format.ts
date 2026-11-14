const pad = (n: number) => String(n).padStart(2, "0");

export const fmtTime = (t: number) => {
  const d = new Date(t);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

export const fmtHM = (t: number) => {
  const d = new Date(t);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const fmtDateTime = (t: number) => {
  const d = new Date(t);
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${fmtTime(t)}`;
};

export const fmtDuration = (s: number) => {
  if (s < 60) return `${Math.round(s)} giây`;
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h ? `${h} giờ ${m} phút` : `${m} phút`;
};

export const fmtAgo = (t: number, now = Date.now()) => {
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s} giây trước`;
  if (s < 3600) return `${Math.round(s / 60)} phút trước`;
  return `${Math.round(s / 3600)} giờ trước`;
};

export const fmtPct = (x: number | null | undefined, digits = 0) =>
  x == null ? "—" : `${(x * 100).toFixed(digits)}%`;

export const fmtNum = (x: number | null | undefined, digits = 2) => (x == null ? "—" : x.toFixed(digits));

/** YYYY-MM-DD theo giờ máy người xem */
export const toDayString = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export const dayBounds = (day: string): [number, number] => {
  const [y, m, d] = day.split("-").map(Number);
  const a = new Date(y, m - 1, d).getTime();
  return [a, a + 86_400_000];
};
