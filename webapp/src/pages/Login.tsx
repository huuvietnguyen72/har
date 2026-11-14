import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context";
import { dataSource } from "../data";

export default function Login() {
  const { session, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (session) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email.trim(), password);
    } catch (err) {
      setError((err as Error).message || "Đăng nhập thất bại");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="login-card" onSubmit={submit}>
        <div className="brand big">
          <svg viewBox="0 0 32 32" width="40" height="40" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M5 17h5l3-7 5 13 3-6h6" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <h1>Giám sát hoạt động</h1>
            <p className="muted">Bộ đeo hông nhận dạng hoạt động &amp; phát hiện té ngã</p>
          </div>
        </div>
        <label>
          Email
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Mật khẩu
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="btn" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button>
        <p className="muted small">
          {dataSource.kind === "mock"
            ? "Bản mẫu: nhập email và mật khẩu bất kỳ."
            : "Tài khoản do nhóm cấp, không tự đăng ký."}
        </p>
      </form>
    </div>
  );
}
