// apiDataSource: fetch + WebSocket tới backend trên VPS.
// WebSocket rớt -> tự hỏi lại /api/status và /api/events mỗi 10 s, đồng thời thử kết nối lại.
import type { DataSource, HarEvent, LiveHandlers, Session, Status } from "../types";

const API = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "/api";
const TOKEN_KEY = "har.session";

export class UnauthorizedError extends Error {}

export function loadSession(): Session | null {
  try {
    const s = JSON.parse(localStorage.getItem(TOKEN_KEY) || "null") as Session | null;
    return s && s.expiresAt > Date.now() ? s : null;
  } catch {
    return null;
  }
}

export function saveSession(s: Session | null) {
  try {
    if (s) localStorage.setItem(TOKEN_KEY, JSON.stringify(s));
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* trình duyệt chặn localStorage: phiên chỉ sống trong tab */
  }
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

async function req<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const s = loadSession();
  if (auth && s) headers.Authorization = `Bearer ${s.token}`;
  const r = await fetch(`${API}${path}`, { ...init, headers: { ...headers, ...(init.headers as any) } });
  if (r.status === 401) {
    if (auth) onUnauthorized();
    const body = await r.json().catch(() => ({}));
    throw new UnauthorizedError(body.detail || "Chưa đăng nhập");
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

function wsUrl(token: string) {
  let base: string;
  if (API.startsWith("http")) base = API.replace(/^http/, "ws").replace(/\/api$/, "");
  else base = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
  return `${base}/ws?token=${encodeURIComponent(token)}`;
}

export const apiDataSource: DataSource = {
  kind: "api",

  async login(email, password) {
    const r = await req<{ access_token: string; expires_at: number; user: Session["user"] }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      false,
    );
    return { token: r.access_token, expiresAt: r.expires_at, user: r.user };
  },

  getStatus: () => req("/status"),
  getStatusHistory: (dev, from, to) => req(`/status/history?dev=${dev}&from=${from}&to=${to}`),
  getSegments: (dev, from, to) => req(`/segments?dev=${dev}&from=${from}&to=${to}`),
  getSummary: (dev, day, days = 1) => req(`/summary?dev=${dev}&day=${day}&days=${days}`),
  getEvents: (dev, limit = 200) => req(`/events?limit=${limit}${dev ? `&dev=${dev}` : ""}`),
  ackEvent: (id, acknowledged = true) =>
    req(`/events/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ acknowledged }) }),
  getMetrics: () => req("/metrics"),

  subscribe(h: LiveHandlers) {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 1000;
    let pollTimer: number | undefined;
    let pingTimer: number | undefined;
    let reconnectTimer: number | undefined;
    const seen = new Set<string>();
    let primed = false;

    const poll = async () => {
      try {
        const [st, evs] = await Promise.all([req<Status[]>("/status"), req<HarEvent[]>("/events?limit=20")]);
        st.forEach((s) => h.onStatus?.(s));
        for (const e of [...evs].reverse()) {
          if (!seen.has(e.id)) {
            seen.add(e.id);
            if (primed) h.onEvent?.({ ...e, new: true });
          }
        }
        primed = true;
      } catch {
        h.onConnection?.("offline");
      }
    };

    const startPolling = () => {
      if (pollTimer) return;
      h.onConnection?.("polling");
      poll();
      pollTimer = window.setInterval(poll, 10_000);
    };
    const stopPolling = () => {
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = undefined;
    };

    const connect = () => {
      const s = loadSession();
      if (!s || closed) return;
      ws = new WebSocket(wsUrl(s.token));
      ws.onopen = () => {
        retry = 1000;
        stopPolling();
        h.onConnection?.("ws");
        pingTimer = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25_000);
      };
      ws.onmessage = (m) => {
        try {
          const msg = JSON.parse(m.data);
          if (msg.type === "status") h.onStatus?.(msg.data);
          if (msg.type === "event") {
            seen.add(msg.data.id);
            h.onEvent?.(msg.data);
          }
        } catch {
          /* bỏ gói lỗi */
        }
      };
      ws.onclose = () => {
        if (pingTimer) window.clearInterval(pingTimer);
        if (closed) return;
        startPolling();
        reconnectTimer = window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30_000);
      };
    };

    // mồi danh sách sự kiện đã có để polling không báo lại sự kiện cũ
    req<HarEvent[]>("/events?limit=50")
      .then((evs) => evs.forEach((e) => seen.add(e.id)))
      .catch(() => {})
      .finally(() => (primed = true));
    connect();

    return () => {
      closed = true;
      stopPolling();
      if (pingTimer) window.clearInterval(pingTimer);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      ws?.close();
    };
  },
};
