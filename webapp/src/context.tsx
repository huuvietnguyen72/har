import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { dataSource } from "./data";
import { loadSession, saveSession, setUnauthorizedHandler } from "./data/api";
import type { HarEvent, Session, Status } from "./types";

// ---------- Đăng nhập ----------
interface AuthCtx {
  session: Session | null;
  login(email: string, password: string): Promise<void>;
  logout(): void;
}
const Auth = createContext<AuthCtx>(null!);
export const useAuth = () => useContext(Auth);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => loadSession());
  const logout = useCallback(() => {
    saveSession(null);
    setSession(null);
  }, []);
  useEffect(() => {
    setUnauthorizedHandler(logout); // không return: React sẽ coi giá trị trả về là hàm dọn dẹp
  }, [logout]);
  useEffect(() => {
    if (!session) return;
    const ms = session.expiresAt - Date.now();
    const t = window.setTimeout(logout, Math.max(0, Math.min(ms, 2 ** 31 - 1)));
    return () => window.clearTimeout(t);
  }, [session, logout]);
  const login = useCallback(async (email: string, password: string) => {
    const s = await dataSource.login(email, password);
    saveSession(s);
    setSession(s);
  }, []);
  return <Auth.Provider value={{ session, login, logout }}>{children}</Auth.Provider>;
}

// ---------- Dữ liệu thời gian thực (trạng thái + cảnh báo mới) ----------
export interface Toast {
  id: string;
  event: HarEvent;
}

interface LiveCtx {
  statuses: Record<string, Status>;
  connection: "ws" | "polling" | "offline" | "connecting";
  lastEvent: HarEvent | null;
  toasts: Toast[];
  dismiss(id: string): void;
  selectedDev: string | null;
  setSelectedDev(dev: string): void;
}
const Live = createContext<LiveCtx>(null!);
export const useLive = () => useContext(Live);

export function LiveProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [statuses, setStatuses] = useState<Record<string, Status>>({});
  const [connection, setConnection] = useState<LiveCtx["connection"]>("connecting");
  const [lastEvent, setLastEvent] = useState<HarEvent | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [selectedDev, setSelectedDev] = useState<string | null>(null);
  const selRef = useRef(selectedDev);
  selRef.current = selectedDev;

  useEffect(() => {
    if (!session) return;
    let alive = true;
    dataSource.getStatus().then((list) => {
      if (!alive) return;
      setStatuses(Object.fromEntries(list.map((s) => [s.dev, s])));
      if (!selRef.current && list[0]) setSelectedDev(list[0].dev);
    }).catch(() => {});
    const unsub = dataSource.subscribe({
      onStatus: (s) => {
        setStatuses((prev) => ({ ...prev, [s.dev]: s }));
        if (!selRef.current) setSelectedDev(s.dev);
      },
      onEvent: (e) => {
        setLastEvent(e);
        if (e.new && !e.cancelled) {
          setToasts((prev) => [...prev.filter((t) => t.id !== e.id), { id: e.id, event: e }].slice(-4));
          if (e.type === "fall" || e.type === "sos") {
            try {
              navigator.vibrate?.([300, 100, 300]);
            } catch {
              /* không hỗ trợ rung */
            }
          }
        }
      },
      onConnection: setConnection,
    });
    return () => {
      alive = false;
      unsub();
    };
  }, [session]);

  const dismiss = useCallback((id: string) => setToasts((p) => p.filter((t) => t.id !== id)), []);
  const value = useMemo(
    () => ({ statuses, connection, lastEvent, toasts, dismiss, selectedDev, setSelectedDev }),
    [statuses, connection, lastEvent, toasts, dismiss, selectedDev],
  );
  return <Live.Provider value={value}>{children}</Live.Provider>;
}

/** Ép component vẽ lại mỗi `ms` để cập nhật "x giây trước". */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [ms]);
  return now;
}
