import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useSession } from "../auth/Session";
import { Logo } from "../ui";

function refusal(e: unknown, withPassword: boolean): string {
  if (!(e instanceof ApiError)) return (e as Error).message;
  if (e.code === "wrong_pin") return "Wrong code or PIN.";
  if (e.code === "wrong_password") return "Wrong email or password.";
  if (e.code === "locked") return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
  // no reason given: still plain words, never "Simple LMS answered 401"
  if (e.status === 401) return withPassword ? "Wrong email or password." : "Wrong code or PIN.";
  if (e.status === 429) return "Too many tries. Wait a minute and try again.";
  if (e.status >= 500) return "Simple LMS couldn't sign you in just now. Try again in a minute.";
  return e.message;
}

/** Code and PIN first (a shared tablet, a phone); email and password for those who have one. */
export function SignIn() {
  const { person, signInWithPin, signInWithPassword } = useSession();
  const [withPassword, setWithPassword] = useState(false);
  const [who, setWho] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (person) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (withPassword) await signInWithPassword(who.trim(), secret);
      else await signInWithPin(who.trim(), secret);
    } catch (err) {
      setError(refusal(err, withPassword));
      setSecret("");
    } finally {
      setBusy(false);
    }
  }

  function switchWay() {
    setWithPassword(!withPassword);
    setWho("");
    setSecret("");
    setError(null);
  }

  return (
    <main className="screen">
      <div className="top"><Logo />Simple LMS<span className="chip">My training</span></div>
      <h1 style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 800 }}>Sign in</h1>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {withPassword ? (
          <>
            <label className="label">Email
              <input className="input" type="email" autoComplete="username" value={who} onChange={(e) => setWho(e.target.value)} required />
            </label>
            <label className="label">Password
              <input className="input" type="password" autoComplete="current-password" value={secret}
                     onChange={(e) => setSecret(e.target.value)} required />
            </label>
          </>
        ) : (
          <>
            <label className="label">Your code
              {/* a shared tablet: nothing about the last person is saved or offered to the next */}
              <input className="input" autoComplete="off" autoCapitalize="characters" autoCorrect="off" spellCheck={false}
                     placeholder="e.g. LL042" value={who} onChange={(e) => setWho(e.target.value)} required />
            </label>
            <label className="label">PIN
              {/* browsers ignore "off" on a password field; "one-time-code" keeps the PIN out of saved passwords */}
              <input className="input" type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={8}
                     value={secret} onChange={(e) => setSecret(e.target.value.replace(/\D/g, ""))} required />
            </label>
          </>
        )}
        {error && <div className="msg r" role="alert">{error}</div>}
        <button type="submit" className="big primary" disabled={busy || !who.trim() || (!withPassword && secret.length < 4)}>
          Sign in</button>
      </form>
      <button type="button" className="link" onClick={switchWay}>
        {withPassword ? "Sign in with your code and PIN" : "Sign in with email and password"}</button>
      <p className="small" style={{ textAlign: "center", color: "var(--color-muted)", fontSize: 13, marginTop: "auto" }}>
        On a shared tablet you're signed out after 15 minutes without a tap. Forgotten your PIN? Ask your manager.
      </p>
    </main>
  );
}
