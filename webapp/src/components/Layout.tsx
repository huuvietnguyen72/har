import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth, useLive } from "../context";
import { dataSource } from "../data";
import { EVENT_VI, LABEL_VI, SOURCE_VI } from "../labels";
import { fmtTime } from "../format";
import type { Label } from "../types";

const NAV = [
  { to: "/", label: "Tổng quan", end: true },
  { to: "/history", label: "Lịch sử" },
  { to: "/alerts", label: "Cảnh báo" },
  { to: "/model", label: "Đánh giá model" },
];

const CONN = {
  ws: { text: "Thời gian thực", tone: "ok" },
  polling: { text: "Hỏi lại mỗi 10 s", tone: "warn" },
  offline: { text: "Mất kết nối cloud", tone: "danger" },
  connecting: { text: "Đang kết nối…", tone: "neutral" },
} as const;

export default function Layout() {
  const { session, logout } = useAuth();
  const { connection, toasts, dismiss } = useLive();
  const nav = useNavigate();
  const c = CONN[connection];
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M5 17h5l3-7 5 13 3-6h6" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>HAR</span>
          {dataSource.kind === "mock" && <span className="badge badge-warn">dữ liệu mẫu</span>}
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-right">
          <span className={`conn conn-${c.tone}`} title="Kênh nhận dữ liệu từ cloud"><i />{c.text}</span>
          <button className="btn-ghost" onClick={logout} title={session?.user.email}>Đăng xuất</button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
      <div className="toasts" aria-live="assertive">
        {toasts.map(({ id, event: e }) => (
          <div key={id} className={`toast toast-${e.severity}`} role="alert">
            <div className="toast-body" onClick={() => { dismiss(id); nav("/alerts"); }}>
              <strong>{e.type === "fall" ? "🚨 " : e.type === "sos" ? "🆘 " : ""}{EVENT_VI[e.type]}</strong>
              <span>{e.dev} · {fmtTime(e.t)}{e.source ? ` · ${SOURCE_VI[e.source] ?? e.source}` : ""}</span>
              {e.prev_label && <span>Trước đó: {LABEL_VI[e.prev_label as Label] ?? e.prev_label}</span>}
            </div>
            <button className="toast-x" onClick={() => dismiss(id)} aria-label="Đóng">×</button>
          </div>
        ))}
      </div>
    </div>
  );
}
