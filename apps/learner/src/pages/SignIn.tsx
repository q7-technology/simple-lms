import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { SignInMethods } from "../api/types";
import { useSession } from "../auth/Session";
import { Logo } from "../ui";

/** What the API says when Microsoft sends someone back without a sign-in. */
const MICROSOFT_SAYS: Record<string, string> = {
  not_matched: "Nobody in Simple LMS has that Microsoft account. Ask your manager to add you.",
  method_off: "Signing in with Microsoft is switched off here.",
  failed: "Signing in with Microsoft didn't work. Try again.",
};
// until the API says, or if it can't: what every install starts with
const USUAL: SignInMethods = { pin: true, password: true, entra: false };

function refusal(e: unknown, withPassword: boolean): string {
  if (!(e instanceof ApiError)) return (e as Error).message;
  if (e.code === "wrong_pin") return "Wrong code or PIN.";
  if (e.code === "wrong_password") return "Wrong email or password.";
  if (e.code === "locked") return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
  if (e.code === "method_off") return /[.!?]$/.test(e.message) ? e.message : `${e.message}.`;
  // no reason given: still plain words, never "Simple LMS answered 401"
  if (e.status === 401) return withPassword ? "Wrong email or password." : "Wrong code or PIN.";
  if (e.status === 429) return "Too many tries. Wait a minute and try again.";
  if (e.status >= 500) return "Simple LMS couldn't sign you in just now. Try again in a minute.";
  return e.message;
}

/** Code and PIN first (a shared tablet, a phone); email and password for
 * those who have one; Microsoft when it is set up. Only the ways an admin
 * has left on. */
export function SignIn() {
  const { person, signInWithPin, signInWithPassword, startEntra, finishEntra } = useSession();
  const [on, setOn] = useState<SignInMethods>(USUAL);
  const [wantPassword, setWantPassword] = useState(false);
  const [who, setWho] = useState("");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { hash } = useLocation();
  const navigate = useNavigate();
  // the hand-off code being used, so it is sent once
  const handedOff = useRef<string | null>(null);

  useEffect(() => {
    let live = true;
    api.get<SignInMethods>("/v1/auth/methods").then((m) => { if (live) setOn(m); }, () => undefined);
    return () => { live = false; };
  }, []);

  // back from Microsoft: /learn/sign-in#entra=<code>, or #entra_error=<why>
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
    finishEntra(code).catch((e) => setError(e instanceof ApiError && e.status === 401
      ? "That Microsoft sign-in has finished or expired. Try again." : refusal(e, false)))
      .finally(() => setBusy(false));
  }, [hash, navigate, finishEntra]);

  if (person) return <Navigate to="/" replace />;
  // the PIN form first, unless PINs are off
  const withPassword = on.password && (wantPassword || !on.pin);
  const withPin = on.pin && !withPassword;

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

  async function microsoft() {
    setBusy(true);
    setError(null);
    try {
      await startEntra();
    } catch (err) {
      setError(refusal(err, false));
      setBusy(false);
    }
  }

  function switchWay() {
    setWantPassword(!withPassword);
    setWho("");
    setSecret("");
    setError(null);
  }

  return (
    <main className="screen">
      <div className="top"><Logo />Simple LMS<span className="chip">My training</span></div>
      <h1 style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 800 }}>Sign in</h1>
      {(withPassword || withPin) && (
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
      )}
      {!withPassword && !withPin && error && <div className="msg r" role="alert">{error}</div>}
      {on.pin && on.password && (
        <button type="button" className="link" onClick={switchWay}>
          {withPassword ? "Sign in with your code and PIN" : "Sign in with email and password"}</button>
      )}
      {on.entra && (
        <button type="button" className={withPassword || withPin ? "big" : "big primary"} disabled={busy}
                onClick={() => void microsoft()}>Sign in with Microsoft</button>
      )}
      {!on.pin && !on.password && !on.entra && (
        <p className="small">Signing in is switched off just now. Ask your manager.</p>
      )}
      {on.pin && (
        <p className="small" style={{ textAlign: "center", color: "var(--color-muted)", fontSize: 13, marginTop: "auto" }}>
          On a shared tablet you're signed out after 15 minutes without a tap. Forgotten your PIN? Ask your manager.
        </p>
      )}
    </main>
  );
}
