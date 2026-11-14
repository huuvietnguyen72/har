import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import Layout from "./components/Layout";
import { AuthProvider, LiveProvider, useAuth } from "./context";
import Alerts from "./pages/Alerts";
import History from "./pages/History";
import Login from "./pages/Login";
import ModelEval from "./pages/ModelEval";
import Overview from "./pages/Overview";
import "./styles.css";

function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  return session ? <>{children}</> : <Navigate to="/login" replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <LiveProvider>
                  <Layout />
                </LiveProvider>
              </RequireAuth>
            }
          >
            <Route index element={<Overview />} />
            <Route path="history" element={<History />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="model" element={<ModelEval />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
