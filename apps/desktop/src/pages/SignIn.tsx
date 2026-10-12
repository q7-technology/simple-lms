import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Problem } from "../ui/Drawer";
import { Logo } from "../ui/Logo";

function refusal(e: unknown): string {
  if (e instanceof ApiError && e.code === "wrong_password") return "Wrong email or password.";
  if (e instanceof ApiError && e.code === "locked") return "Too many wrong passwords. Try again in 15 minutes.";
  return (e as Error).message;
}

export function SignIn() {
  const { me, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (err) {
      setError(refusal(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm flex flex-col gap-4" style={{ boxShadow: "var(--shadow-lift)" }}>
        <div className="brand"><Logo />Simple LMS</div>
        <h1 className="m-0 text-2xl font-extrabold">Sign in</h1>
        <label className="label">Email
          <input className="field" type="email" autoComplete="username" value={email}
                 onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="label">Password
          <input className="field" type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <Problem error={error} />
        <button type="submit" className="btn primary" disabled={busy}>Sign in</button>
      </form>
    </main>
  );
}
