/**
 * HAR cloud trên Cloudflare: một Worker phục vụ API /api/* (dữ liệu trong D1) và web app (file tĩnh).
 *
 * Giữ nguyên hợp đồng API của backend FastAPI cũ (backend/api), nên Pi (har-uplink) và web app không phải đổi:
 * - Pi gọi /api/ingest/* với header X-Device-Key; mọi đường idempotent (gửi lại outbox không tạo bản trùng).
 * - Web app gọi /api/* với JWT (Authorization: Bearer).
 * Khác: không có WebSocket (/ws); web app build với VITE_REALTIME=polling và hỏi lại định kỳ.
 */
import { sha256Hex, signJwt, verifyJwt, verifyPassword } from "./crypto";

export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  JWT_SECRET: string;
  JWT_EXPIRE_HOURS?: string;
  STATUS_STALE_S?: string;
  STATUS_LOG_EVERY_S?: string;
  TZ_OFFSET_MIN?: string; // múi giờ chia "ngày" cho Lịch sử; Việt Nam = 420
  CORS_ORIGINS?: string; // chỉ khi chạy web app dev ở cổng khác
  PI_OFFLINE_MIN?: string; // Pi im lặng quá số phút này -> cảnh báo "Pi mất kết nối" (Cron Trigger)
  TELEGRAM_BOT_TOKEN?: string; // bí mật (wrangler secret put): cùng bot với har-notify trên Pi
  TELEGRAM_CHAT_ID?: string;
}

const LABELS = ["stand", "sit", "lie", "walk", "stairs_up", "stairs_down", "fall"];
const EVENT_TYPES = ["fall", "sos", "low_battery", "offline"];
const SEVERITIES = ["high", "medium", "info"];
const SOURCES = ["threshold", "model", "both", "device", "edge"];
const MAX_RANGE_MS = 8 * 24 * 3600 * 1000;

class HttpError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

const json = (data: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json; charset=utf-8", ...headers } });
const nowMs = () => Date.now();
const num = (v: string | undefined, d: number) => (v !== undefined && v !== "" && !Number.isNaN(Number(v)) ? Number(v) : d);

// ---------------- kiểm tra dữ liệu vào (thay pydantic) ----------------
type Spec = Record<string, (v: unknown, path: string) => unknown>;
const fail = (path: string, msg: string): never => {
  throw new HttpError(422, `${path}: ${msg}`);
};
const opt = (f: (v: unknown, p: string) => unknown) => (v: unknown, p: string) => (v === undefined || v === null ? null : f(v, p));
const str = (max?: number) => (v: unknown, p: string) =>
  typeof v === "string" ? (max && v.length > max ? fail(p, `dài quá ${max} ký tự`) : v) : fail(p, "phải là chuỗi");
const int = (v: unknown, p: string) => (typeof v === "number" && Number.isInteger(v) ? v : fail(p, "phải là số nguyên"));
const float = (lo?: number, hi?: number) => (v: unknown, p: string) => {
  if (typeof v !== "number" || !Number.isFinite(v)) return fail(p, "phải là số");
  if ((lo !== undefined && v < lo) || (hi !== undefined && v > hi)) return fail(p, `ngoài khoảng ${lo}..${hi}`);
  return v;
};
const bool = (v: unknown, p: string) => (typeof v === "boolean" ? v : fail(p, "phải là true/false"));
const oneOf = (xs: string[]) => (v: unknown, p: string) => (typeof v === "string" && xs.includes(v) ? v : fail(p, `phải là một trong ${xs.join(", ")}`));
const obj = (v: unknown, p: string) => (v && typeof v === "object" && !Array.isArray(v) ? v : fail(p, "phải là object"));
const withDefault = (f: (v: unknown, p: string) => unknown, d: unknown) => (v: unknown, p: string) => (v === undefined || v === null ? d : f(v, p));

function check(body: unknown, spec: Spec, path = "body"): Record<string, any> {
  const b = obj(body, path) as Record<string, unknown>;
  const out: Record<string, any> = {};
  for (const [k, f] of Object.entries(spec)) out[k] = f(b[k], `${path}.${k}`);
  return out;
}
const need = (f: (v: unknown, p: string) => unknown) => (v: unknown, p: string) => (v === undefined ? fail(p, "bắt buộc") : f(v, p));
function list(v: unknown, p: string, max: number): unknown[] {
  if (!Array.isArray(v)) fail(p, "phải là danh sách");
  if ((v as unknown[]).length > max) fail(p, `tối đa ${max} phần tử`);
  return v as unknown[];
}

const STATUS_IN: Spec = {
  dev: need(str()), t: need(int), label: opt(oneOf(LABELS)), conf: opt(float(0, 1)), online: withDefault(bool, true),
  battery_v: opt(float()), battery_pct: opt(float(0, 100)), temp_c: opt(float()), rh: opt(float()), rssi: opt(int),
  model: opt(str()), fw: opt(str()),
};
const SEGMENT_IN: Spec = { dev: need(str()), start: need(int), end: need(int), label: need(oneOf(LABELS)), conf_avg: opt(float(0, 1)) };
const EVENT_IN: Spec = {
  id: need(str(64)), dev: need(str()), t: need(int), type: need(oneOf(EVENT_TYPES)), severity: withDefault(oneOf(SEVERITIES), "info"),
  source: opt(oneOf(SOURCES)), prob: opt(float(0, 1)), prev_label: opt(str()), battery_pct: opt(float()),
  cancelled: withDefault(bool, false), delivered_late: withDefault(bool, false),
};
const METRIC_IN: Spec = {
  experiment: need(str(32)), model: need(str()), features: opt(str()), window_s: opt(float()), accuracy: opt(float()),
  macro_f1: opt(float()), f1_per_class: opt(obj), confusion: opt(obj), n_windows: opt(int), n_subjects: opt(int), extra: opt(obj),
};
const SYSTEM_METRIC_IN: Spec = {
  dev: need(str()), day: need((v, p) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : fail(p, "dạng YYYY-MM-DD"))),
  latency: opt(obj), packet_loss: opt(float()), packets: opt(int), battery_hours: opt(float()), extra: opt(obj),
};

// ---------------- chuyển dòng D1 -> JSON giống backend cũ ----------------
const B = (x: unknown) => Boolean(x);
const J = (x: unknown) => (typeof x === "string" ? JSON.parse(x) : x ?? null);

function statusOut(env: Env, st: any, device: any | null) {
  const stale = nowMs() - st.received_at > num(env.STATUS_STALE_S, 30) * 1000;
  return {
    dev: st.dev, t: st.t, label: st.label, conf: st.conf, online: B(st.online) && !stale, battery_v: st.battery_v,
    battery_pct: st.battery_pct, temp_c: st.temp_c, rh: st.rh, rssi: st.rssi, model: st.model, received_at: st.received_at,
    alias: device?.alias ?? null, fw: device?.fw ?? null,
  };
}
const eventOut = (e: any) => ({ ...e, cancelled: B(e.cancelled), acknowledged: B(e.acknowledged), delivered_late: B(e.delivered_late) });
const metricOut = (m: any) => ({ ...m, f1_per_class: J(m.f1_per_class), confusion: J(m.confusion), extra: J(m.extra) });
const systemOut = (s: any) => ({ ...s, latency: J(s.latency), extra: J(s.extra) });

// ---------------- xác thực ----------------
async function currentDevice(req: Request, env: Env) {
  const key = req.headers.get("x-device-key");
  if (!key) throw new HttpError(401, "Thiếu X-Device-Key");
  const dev = await env.DB.prepare("SELECT * FROM devices WHERE key_hash = ?").bind(await sha256Hex(key)).first();
  if (!dev) throw new HttpError(401, "API key không hợp lệ");
  return dev as any;
}

async function currentUser(req: Request, env: Env) {
  const h = req.headers.get("authorization") || "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  if (!m) throw new HttpError(401, "Thiếu JWT");
  const claims = await verifyJwt(m[1], env.JWT_SECRET);
  if (!claims) throw new HttpError(401, "Token không hợp lệ hoặc đã hết hạn");
  const user = await env.DB.prepare("SELECT email, role FROM users WHERE email = ?").bind(claims.sub).first();
  if (!user) throw new HttpError(401, "Tài khoản không tồn tại");
  return user as { email: string; role: string };
}

const checkDev = (device: any, dev: string) => {
  if (dev !== device.dev) throw new HttpError(403, `API key của ${device.dev} không được ghi cho ${dev}`);
};

async function readJson(req: Request): Promise<unknown> {
  try {
    return await req.json();
  } catch {
    throw new HttpError(422, "Thân request không phải JSON");
  }
}

// ---------------- ingest (Pi) ----------------
/** Pi (har-uplink) gọi mỗi 60 s, kể cả khi bộ đeo tắt: cloud biết Pi còn sống. */
async function ingestHeartbeat(req: Request, env: Env) {
  const device = await currentDevice(req, env);
  const now = nowMs();
  await env.DB.prepare("UPDATE devices SET pi_seen_at = ? WHERE dev = ?").bind(now, device.dev).run();
  return json({ ok: true, received_at: now });
}

async function ingestStatus(req: Request, env: Env) {
  const device = await currentDevice(req, env);
  const b = check(await readJson(req), STATUS_IN);
  checkDev(device, b.dev);
  const now = nowMs();
  const stmts = [
    env.DB.prepare("UPDATE devices SET pi_seen_at = ? WHERE dev = ?").bind(now, b.dev),
    env.DB.prepare(
      `INSERT INTO status (dev, t, label, conf, online, battery_v, battery_pct, temp_c, rh, rssi, model, received_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(dev) DO UPDATE SET t=excluded.t, label=excluded.label, conf=excluded.conf, online=excluded.online,
         battery_v=excluded.battery_v, battery_pct=excluded.battery_pct, temp_c=excluded.temp_c, rh=excluded.rh,
         rssi=excluded.rssi, model=excluded.model, received_at=excluded.received_at`,
    ).bind(b.dev, b.t, b.label, b.conf, b.online ? 1 : 0, b.battery_v, b.battery_pct, b.temp_c, b.rh, b.rssi, b.model, now),
  ];
  if (b.fw || b.model) {
    stmts.push(env.DB.prepare("UPDATE devices SET fw = COALESCE(?, fw), model = COALESCE(?, model) WHERE dev = ?").bind(b.fw, b.model, b.dev));
  }
  // lịch sử thưa: tối đa 1 dòng mỗi STATUS_LOG_EVERY_S
  const everyMs = num(env.STATUS_LOG_EVERY_S, 60) * 1000;
  const last = await env.DB.prepare("SELECT MAX(t) AS t FROM status_log WHERE dev = ?").bind(b.dev).first<{ t: number | null }>();
  if (last?.t == null || b.t - last.t >= everyMs) {
    stmts.push(
      env.DB.prepare("INSERT INTO status_log (dev, t, online, battery_v, battery_pct, temp_c, rh) VALUES (?, ?, ?, ?, ?, ?, ?)")
        .bind(b.dev, b.t, b.online ? 1 : 0, b.battery_v, b.battery_pct, b.temp_c, b.rh),
    );
  }
  await env.DB.batch(stmts);
  return json({ ok: true, received_at: now });
}

async function ingestSegments(req: Request, env: Env) {
  const device = await currentDevice(req, env);
  const body = obj(await readJson(req), "body") as any;
  const segs = list(body.segments, "body.segments", 1000).map((s, i) => check(s, SEGMENT_IN, `body.segments[${i}]`));
  for (const s of segs) {
    checkDev(device, s.dev);
    if (s.end < s.start) throw new HttpError(422, "end phải ≥ start");
  }
  let inserted = 0;
  if (segs.length) {
    const res = await env.DB.batch(
      segs.map((s) =>
        env.DB.prepare(`INSERT INTO segments (dev, start, "end", label, conf_avg) VALUES (?, ?, ?, ?, ?) ON CONFLICT(dev, start) DO NOTHING`)
          .bind(s.dev, s.start, s.end, s.label, s.conf_avg),
      ),
    );
    inserted = res.reduce((n, r) => n + (r.meta?.changes ?? 0), 0);
  }
  return json({ ok: true, received: segs.length, inserted });
}

async function ingestEvents(req: Request, env: Env) {
  const device = await currentDevice(req, env);
  const body = obj(await readJson(req), "body") as any;
  const evs = list(body.events, "body.events", 500).map((e, i) => check(e, EVENT_IN, `body.events[${i}]`));
  for (const e of evs) checkDev(device, e.dev);
  const now = nowMs();
  const ids = evs.map((e) => e.id);
  let existing = new Set<string>();
  if (ids.length) {
    const r = await env.DB.prepare(`SELECT id FROM events WHERE id IN (${ids.map(() => "?").join(",")})`).bind(...ids).all<{ id: string }>();
    existing = new Set(r.results.map((x) => x.id));
    // cùng id gửi lại: cập nhật trạng thái (ví dụ đã hủy) nhưng giữ cờ "đã xử lý" của người dùng
    await env.DB.batch(
      evs.map((e) =>
        env.DB.prepare(
          `INSERT INTO events (id, dev, t, type, severity, source, prob, prev_label, battery_pct, cancelled, delivered_late, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET t=excluded.t, type=excluded.type, severity=excluded.severity, source=excluded.source,
             prob=excluded.prob, prev_label=excluded.prev_label, battery_pct=excluded.battery_pct,
             cancelled=excluded.cancelled, delivered_late=excluded.delivered_late`,
        ).bind(e.id, e.dev, e.t, e.type, e.severity, e.source, e.prob, e.prev_label, e.battery_pct, e.cancelled ? 1 : 0, e.delivered_late ? 1 : 0, now),
      ),
    );
  }
  return json({ ok: true, received: evs.length, new: ids.filter((i) => !existing.has(i)).length });
}

async function ingestMetrics(req: Request, env: Env) {
  await currentDevice(req, env);
  const m = check(await readJson(req), METRIC_IN);
  const s = (x: unknown) => (x == null ? null : JSON.stringify(x));
  await env.DB.prepare(
    `INSERT INTO metrics (experiment, model, features, window_s, accuracy, macro_f1, f1_per_class, confusion, n_windows, n_subjects, extra, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(experiment) DO UPDATE SET model=excluded.model, features=excluded.features, window_s=excluded.window_s,
       accuracy=excluded.accuracy, macro_f1=excluded.macro_f1, f1_per_class=excluded.f1_per_class, confusion=excluded.confusion,
       n_windows=excluded.n_windows, n_subjects=excluded.n_subjects, extra=excluded.extra, created_at=excluded.created_at`,
  ).bind(m.experiment, m.model, m.features, m.window_s, m.accuracy, m.macro_f1, s(m.f1_per_class), s(m.confusion), m.n_windows, m.n_subjects, s(m.extra), new Date().toISOString()).run();
  return json({ ok: true, experiment: m.experiment });
}

async function ingestSystemMetrics(req: Request, env: Env) {
  const device = await currentDevice(req, env);
  const body = obj(await readJson(req), "body") as any;
  const items = list(body.items, "body.items", 100).map((x, i) => check(x, SYSTEM_METRIC_IN, `body.items[${i}]`));
  for (const it of items) checkDev(device, it.dev);
  const s = (x: unknown) => (x == null ? null : JSON.stringify(x));
  if (items.length) {
    await env.DB.batch(
      items.map((it) =>
        env.DB.prepare(
          `INSERT INTO system_metrics (dev, day, latency, packet_loss, packets, battery_hours, extra) VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(dev, day) DO UPDATE SET latency=excluded.latency, packet_loss=excluded.packet_loss, packets=excluded.packets,
             battery_hours=excluded.battery_hours, extra=excluded.extra`,
        ).bind(it.dev, it.day, s(it.latency), it.packet_loss, it.packets, it.battery_hours, s(it.extra)),
      ),
    );
  }
  return json({ ok: true, received: items.length });
}

// ---------------- đọc (web app) ----------------
function qInt(url: URL, name: string, def: number | null, lo?: number, hi?: number): number | null {
  const v = url.searchParams.get(name);
  if (v === null || v === "") return def;
  const n = Number(v);
  if (!Number.isInteger(n)) throw new HttpError(422, `${name}: phải là số nguyên`);
  if ((lo !== undefined && n < lo) || (hi !== undefined && n > hi)) throw new HttpError(422, `${name}: ngoài khoảng ${lo}..${hi}`);
  return n;
}
function range(url: URL, defaultMs: number): [number, number] {
  const to = qInt(url, "to", null) ?? nowMs();
  const frm = qInt(url, "from", null) ?? to - defaultMs;
  if (to < frm || to - frm > MAX_RANGE_MS) throw new HttpError(422, "Khoảng thời gian không hợp lệ (tối đa 8 ngày)");
  return [frm, to];
}
const needDev = (url: URL) => url.searchParams.get("dev") || (() => { throw new HttpError(422, "dev: bắt buộc"); })();

async function segmentsBetween(env: Env, dev: string, frm: number, to: number) {
  const r = await env.DB.prepare(`SELECT dev, start, "end", label, conf_avg FROM segments WHERE dev = ? AND "end" > ? AND start < ? ORDER BY start`)
    .bind(dev, frm, to).all();
  return r.results as any[];
}

/** [đầu ngày, đầu ngày hôm sau) theo múi giờ cố định (Việt Nam không đổi giờ mùa hè). */
function dayBounds(day: string, offMin: number): [number, number] {
  const [y, m, d] = day.split("-").map(Number);
  const a = Date.UTC(y, m - 1, d) - offMin * 60_000;
  return [a, a + 86_400_000];
}
function localToday(offMin: number): string {
  return new Date(nowMs() + offMin * 60_000).toISOString().slice(0, 10);
}
function shiftDay(day: string, delta: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10);
}
const r1 = (x: number) => Math.round(x * 10) / 10;

async function summarizeDay(env: Env, dev: string, day: string) {
  const [a, b] = dayBounds(day, num(env.TZ_OFFSET_MIN, 420));
  const seconds: Record<string, number> = Object.fromEntries(LABELS.map((l) => [l, 0]));
  let online = 0;
  for (const s of await segmentsBetween(env, dev, a, b)) {
    const dur = (Math.min(s.end, b) - Math.max(s.start, a)) / 1000;
    if (dur > 0) {
      seconds[s.label] = (seconds[s.label] ?? 0) + dur;
      online += dur;
    }
  }
  const evs = (await env.DB.prepare("SELECT type, cancelled FROM events WHERE dev = ? AND t >= ? AND t < ?").bind(dev, a, b).all<any>()).results;
  return {
    dev, day, seconds: Object.fromEntries(Object.entries(seconds).map(([k, v]) => [k, r1(v)])), online_s: r1(online),
    n_alerts: evs.filter((e) => (e.type === "fall" || e.type === "sos") && !e.cancelled).length,
    n_cancelled: evs.filter((e) => e.cancelled).length,
  };
}

async function allStatus(env: Env) {
  const r = await env.DB.prepare("SELECT s.*, d.alias AS d_alias, d.fw AS d_fw FROM status s LEFT JOIN devices d ON d.dev = s.dev").all<any>();
  return r.results.map((row) => statusOut(env, row, { alias: row.d_alias, fw: row.d_fw }));
}

// ---------------- định tuyến ----------------
async function route(req: Request, env: Env, url: URL): Promise<Response> {
  const p = url.pathname.replace(/\/+$/, "") || "/";
  const m = req.method;

  if (p === "/api/health" && m === "GET") {
    await env.DB.prepare("SELECT 1").first();
    return json({ ok: true, ws_clients: 0 });
  }
  // --- Pi ---
  if (m === "POST" && p === "/api/ingest/status") return ingestStatus(req, env);
  if (m === "POST" && p === "/api/ingest/heartbeat") return ingestHeartbeat(req, env);
  if (m === "POST" && p === "/api/ingest/segments") return ingestSegments(req, env);
  if (m === "POST" && p === "/api/ingest/events") return ingestEvents(req, env);
  if (m === "POST" && p === "/api/ingest/metrics") return ingestMetrics(req, env);
  if (m === "POST" && p === "/api/ingest/system_metrics") return ingestSystemMetrics(req, env);

  // --- đăng nhập ---
  if (m === "POST" && p === "/api/auth/login") {
    const b = check(await readJson(req), { email: need(str()), password: need(str()) });
    const email = String(b.email).trim().toLowerCase();
    const user = await env.DB.prepare("SELECT * FROM users WHERE email = ?").bind(email).first<any>();
    if (!user || !(await verifyPassword(String(b.password), user.password_hash))) throw new HttpError(401, "Sai email hoặc mật khẩu");
    const expMs = nowMs() + num(env.JWT_EXPIRE_HOURS, 12) * 3600_000;
    const token = await signJwt({ sub: user.email, role: user.role, exp: Math.floor(expMs / 1000) }, env.JWT_SECRET);
    return json({ access_token: token, token_type: "bearer", expires_at: expMs, user: { email: user.email, role: user.role } });
  }
  if (m === "GET" && p === "/api/auth/me") return json(await currentUser(req, env));

  // --- web app (cần JWT) ---
  if (p.startsWith("/api/")) {
    const user = await currentUser(req, env);
    if (m === "GET" && p === "/api/devices") {
      const r = await env.DB.prepare("SELECT dev, alias, position, fw, model, created_at, pi_seen_at, pi_offline_since FROM devices").all();
      return json(r.results);
    }
    if (m === "GET" && p === "/api/status") return json(await allStatus(env));
    if (m === "GET" && p === "/api/live") {
      // dashboard hỏi định kỳ: trạng thái + cảnh báo mới nhất trong MỘT request (đỡ tốn hạn mức request)
      const limit = qInt(url, "limit", 20, 1, 100);
      const [st, evs] = await Promise.all([
        allStatus(env),
        env.DB.prepare("SELECT * FROM events ORDER BY t DESC LIMIT ?").bind(limit).all(),
      ]);
      return json({ status: st, events: evs.results.map(eventOut) });
    }
    if (m === "GET" && p === "/api/status/history") {
      const dev = needDev(url);
      const [frm, to] = range(url, 24 * 3600_000);
      const r = await env.DB.prepare("SELECT dev, t, online, battery_v, battery_pct, temp_c, rh FROM status_log WHERE dev = ? AND t >= ? AND t < ? ORDER BY t")
        .bind(dev, frm, to).all<any>();
      return json(r.results.map((x) => ({ ...x, online: B(x.online) })));
    }
    if (m === "GET" && p === "/api/segments") {
      const dev = needDev(url);
      const [frm, to] = range(url, 3600_000);
      return json(await segmentsBetween(env, dev, frm, to));
    }
    if (m === "GET" && p === "/api/summary") {
      const dev = needDev(url);
      const days = qInt(url, "days", 1, 1, 31)!;
      const dayParam = url.searchParams.get("day");
      if (dayParam && !/^\d{4}-\d{2}-\d{2}$/.test(dayParam)) throw new HttpError(422, "day: dạng YYYY-MM-DD");
      const last = dayParam || localToday(num(env.TZ_OFFSET_MIN, 420));
      const out = [];
      for (let i = days - 1; i >= 0; i--) out.push(await summarizeDay(env, dev, shiftDay(last, -i)));
      return json(out);
    }
    if (m === "GET" && p === "/api/events") {
      const where: string[] = [];
      const args: unknown[] = [];
      const dev = url.searchParams.get("dev");
      if (dev) (where.push("dev = ?"), args.push(dev));
      const frm = qInt(url, "from", null);
      const to = qInt(url, "to", null);
      if (frm !== null) (where.push("t >= ?"), args.push(frm));
      if (to !== null) (where.push("t < ?"), args.push(to));
      const limit = qInt(url, "limit", 200, 1, 1000);
      const r = await env.DB.prepare(`SELECT * FROM events ${where.length ? "WHERE " + where.join(" AND ") : ""} ORDER BY t DESC LIMIT ?`)
        .bind(...args, limit).all();
      return json(r.results.map(eventOut));
    }
    const ev = p.match(/^\/api\/events\/([^/]+)$/);
    if (m === "PATCH" && ev) {
      const id = decodeURIComponent(ev[1]);
      const b = check(await readJson(req).catch(() => ({})), { acknowledged: withDefault(bool, true) });
      const cur = await env.DB.prepare("SELECT id FROM events WHERE id = ?").bind(id).first();
      if (!cur) throw new HttpError(404, "Không có sự kiện này");
      await env.DB.prepare("UPDATE events SET acknowledged = ?, acknowledged_at = ?, acknowledged_by = ? WHERE id = ?")
        .bind(b.acknowledged ? 1 : 0, b.acknowledged ? new Date().toISOString() : null, b.acknowledged ? user.email : null, id).run();
      return json(eventOut(await env.DB.prepare("SELECT * FROM events WHERE id = ?").bind(id).first()));
    }
    if (m === "GET" && p === "/api/metrics") {
      const [ex, sys, devs] = await env.DB.batch([
        env.DB.prepare("SELECT * FROM metrics ORDER BY experiment"),
        env.DB.prepare("SELECT * FROM system_metrics ORDER BY day DESC LIMIT 60"),
        env.DB.prepare("SELECT dev, model FROM devices"),
      ]);
      return json({
        experiments: (ex.results as any[]).map(metricOut),
        system: (sys.results as any[]).map(systemOut),
        running_models: Object.fromEntries((devs.results as any[]).map((d) => [d.dev, d.model])),
      });
    }
    throw new HttpError(404, "Không có đường này");
  }
  if (p === "/ws") throw new HttpError(426, "Bản Cloudflare không có WebSocket; web app tự hỏi lại định kỳ");
  return env.ASSETS.fetch(req); // web app (file tĩnh, SPA)
}

function cors(env: Env, req: Request, res: Response): Response {
  const origins = (env.CORS_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  const origin = req.headers.get("origin");
  if (!origin || !origins.includes(origin)) return res;
  const h = new Headers(res.headers);
  h.set("access-control-allow-origin", origin);
  h.set("access-control-allow-headers", "authorization, content-type, x-device-key");
  h.set("access-control-allow-methods", "GET, POST, PATCH, OPTIONS");
  h.set("vary", "origin");
  return new Response(res.body, { status: res.status, headers: h });
}

// ---------------- Cron: cảnh báo "Pi mất kết nối" ----------------
const hhmm = (t: number, offMin: number) => new Date(t + offMin * 60_000).toISOString().slice(11, 16);
const fmtDur = (ms: number) => {
  const m = Math.round(ms / 60_000);
  return m < 60 ? `${m} phút` : `${Math.floor(m / 60)} giờ ${m % 60} phút`;
};

// TELEGRAM_CHAT_ID: một hoặc nhiều chat ngăn bằng dấu phẩy (giống edge/.env); bỏ khoảng trắng, ô rỗng, trùng
export const chatIds = (v?: string) => [...new Set((v ?? "").split(",").map((c) => c.trim()).filter(Boolean))];

/** Gửi cho mọi người nhận; một người lỗi (chặn bot, sai chat ID) không chặn người khác. true nếu ít nhất một người nhận được. */
async function telegram(env: Env, text: string): Promise<boolean> {
  const chats = chatIds(env.TELEGRAM_CHAT_ID);
  if (!env.TELEGRAM_BOT_TOKEN || !chats.length) return false;
  const results = await Promise.all(chats.map(async (chat_id) => {
    try {
      const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ chat_id, text, parse_mode: "HTML", disable_web_page_preview: true }),
      });
      if (!r.ok) console.error("Telegram", chat_id, r.status, (await r.text()).slice(0, 200)); // không in token
      return r.ok;
    } catch (e) {
      console.error("Telegram", chat_id, String(e).slice(0, 200));
      return false;
    }
  }));
  return results.some(Boolean);
}

/**
 * Pi không gọi cloud quá PI_OFFLINE_MIN phút (tắt, mất điện, mất Internet) -> báo một lần qua Telegram và ghi sự kiện
 * "offline" (nguồn cloud) cho dashboard; Pi gọi lại -> báo đã kết nối lại. Cảnh báo "bộ đeo mất kết nối" vẫn do
 * Pi gửi (Pi còn sống mới biết bộ đeo im).
 */
export async function checkPiOffline(env: Env, now = nowMs()) {
  const limitMs = num(env.PI_OFFLINE_MIN, 10) * 60_000;
  const off = num(env.TZ_OFFSET_MIN, 420);
  const devs = (await env.DB.prepare("SELECT dev, alias, pi_seen_at, pi_offline_since FROM devices WHERE pi_seen_at IS NOT NULL").all<any>()).results;
  const out: string[] = [];
  for (const d of devs) {
    const name = d.alias ? `${d.alias} (${d.dev})` : d.dev;
    const silent = now - d.pi_seen_at;
    if (silent > limitMs && d.pi_offline_since == null) {
      await env.DB.batch([
        env.DB.prepare("UPDATE devices SET pi_offline_since = ? WHERE dev = ?").bind(d.pi_seen_at, d.dev),
        env.DB.prepare(
          `INSERT INTO events (id, dev, t, type, severity, source, cancelled, received_at) VALUES (?, ?, ?, 'offline', 'info', 'cloud', 0, ?)
           ON CONFLICT(id) DO NOTHING`,
        ).bind(`${d.dev}-pi-offline-${d.pi_seen_at}`, d.dev, d.pi_seen_at, now),
      ]);
      await telegram(env, `📴 <b>Pi mất kết nối</b>\nThiết bị: <code>${name}</code>\nKhông có dữ liệu từ Pi từ ${hhmm(d.pi_seen_at, off)} ` +
        `(${fmtDur(silent)}).\nBộ đeo vẫn tự kêu còi khi té, nhưng không có Telegram, dashboard và model cho tới khi Pi chạy lại. ` +
        `Kiểm tra Pi còn điện và Internet.`);
      out.push(`${d.dev}: offline`);
    } else if (silent <= limitMs && d.pi_offline_since != null) {
      await env.DB.prepare("UPDATE devices SET pi_offline_since = NULL WHERE dev = ?").bind(d.dev).run();
      await telegram(env, `✅ <b>Pi đã kết nối lại</b>\nThiết bị: <code>${name}</code>\nMất kết nối khoảng ${fmtDur(d.pi_seen_at - d.pi_offline_since)} ` +
        `(từ ${hhmm(d.pi_offline_since, off)} đến ${hhmm(d.pi_seen_at, off)}).`);
      out.push(`${d.dev}: online again`);
    }
  }
  return out;
}

export default {
  async scheduled(_ev: ScheduledController, env: Env) {
    const r = await checkPiOffline(env); // chờ xong mới kết thúc lượt Cron
    if (r.length) console.log("pi-offline:", r.join(", "));
  },

  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return cors(env, req, new Response(null, { status: 204 }));
    try {
      return cors(env, req, await route(req, env, url));
    } catch (e) {
      if (e instanceof HttpError) return cors(env, req, json({ detail: e.detail }, e.status));
      console.error(e);
      return cors(env, req, json({ detail: "Lỗi máy chủ" }, 500));
    }
  },
} satisfies ExportedHandler<Env>;
