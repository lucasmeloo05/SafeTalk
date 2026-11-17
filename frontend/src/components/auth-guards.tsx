import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/auth-context";

function SessionLoading() {
  return (
    <main className="session-loading" role="status" aria-live="polite">
      <span className="session-loading__mark">S</span>
      <span>Verificando sua sessão…</span>
    </main>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading, sessionNotice } = useAuth();
  const location = useLocation();

  if (isLoading) return <SessionLoading />;
  if (!user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location, sessionNotice }}
      />
    );
  }
  return children;
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <SessionLoading />;
  if (user) return <Navigate to="/app" replace />;
  return children;
}
