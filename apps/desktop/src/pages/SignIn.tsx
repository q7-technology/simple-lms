import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { SignInMethods } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { Logo } from "../ui/Logo";

/** What the API says when Microsoft sends someone back without a sign-in. */
const MICROSOFT_SAYS: Record<string, string> = {
  not_matched: "Nobody in Simple LMS has that Microsoft account. Ask your manager to add you.",
  method_off: "Signing in with Microsoft is switched off here.",
  failed: "Signing in with Microsoft didn't work. Try again.",
};
// until the API says, or if it can't: what every install starts with
const USUAL: SignInMethods = { pin: true, password: true, entra: false };

function refusal(e: unknown): string {
  if (e instanceof ApiError && e.code === "wrong_password") return "Wrong email or password.";
  if (e instanceof ApiError && e.code === "locked") return "Too many wrong passwords. Try again in 15 minutes.";
  if (e instanceof ApiError && e.code === "method_off") return /[.!?]$/.test(e.message) ? e.message : `${e.message}.`;
  if (e instanceof ApiError && e.status === 401) return "That Microsoft sign-in has finished or expired. Try again.";
  return (e as Error).message;
}

export function SignIn() {
  const { me, signIn, startEntra, finishEntra } = useAuth();
  const ways = useLoad(() => api.get<SignInMethods>("/v1/auth/methods"), []);
  const { hash } = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // the hand-off code being used, so it is sent once
  const handedOff = useRef<string | null>(null);

  // back from Microsoft: /sign-in#entra=<code>, or #entra_error=<why>
  useEffect(() => {
    const back = new URLSearchParams(hash.slice(1));
    const code = back.get("entra");
    const why = back.get("entra_error");
    if (!code && !why) return;
    // the code leaves the address bar and the history at once
    navigate("/sign-in", { replace: true });
    if (!code) {
      setError(MICROSOFT_SAYS[why!] ?? MICROSOFT_SAYS.failed);
      return;
    }
    if (handedOff.current === code) return;
    handedOff.current = code;
    setBusy(true);
    setError(null);
    finishEntra(code).catch((e) => setError(refusal(e))).finally(() => setBusy(false));
  }, [hash, navigate, finishEntra]);

  if (me) return <Navigate to="/" replace />;
  const on = ways.data ?? USUAL;

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

  async function microsoft() {
    setBusy(true);
    setError(null);
    try {
      await startEntra();
    } catch (err) {
      setError(refusal(err));
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen grid place-items-center p-6">
      <form onSubmit={submit} className="card w-full max-w-sm flex flex-col gap-4" style={{ boxShadow: "var(--shadow-lift)" }}>
        <div className="brand"><Logo />Simple LMS</div>
        <h1 className="m-0 text-2xl font-extrabold">Sign in</h1>
        {on.password && (
          <>
            <label className="label">Email
              <input className="field" type="email" autoComplete="username" value={email}
                     onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label className="label">Password
              <input className="field" type="password" autoComplete="current-password" value={password}
                     onChange={(e) => setPassword(e.target.value)} required />
            </label>
          </>
        )}
        <Problem error={error} />
        {on.password && <button type="submit" className="btn primary" disabled={busy}>Sign in</button>}
        {on.entra && (
          <button type="button" className={on.password ? "btn" : "btn primary"} disabled={busy}
                  onClick={() => void microsoft()}>Sign in with Microsoft</button>
        )}
        {!on.password && !on.entra && (
          <div className="small">Signing in to the desktop is switched off. Someone with the server's command line
            can turn it back on: <code>lms clear-setting sign_in_password</code>.</div>
        )}
      </form>
    </main>
  );
}
