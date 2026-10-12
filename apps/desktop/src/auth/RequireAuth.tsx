import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";

export function RequireAuth() {
  const { ready, me, trouble, retry } = useAuth();
  if (!ready) return <div className="p-6 small">Loading…</div>;
  if (!me && trouble) {
    return (
      <main className="min-h-screen grid place-items-center p-6">
        <div className="card w-full max-w-sm flex flex-col gap-4">
          <div className="msg r" role="alert">{trouble}</div>
          <button type="button" className="btn primary" onClick={retry}>Try again</button>
        </div>
      </main>
    );
  }
  if (!me) return <Navigate to="/sign-in" replace />;
  return <Outlet />;
}
