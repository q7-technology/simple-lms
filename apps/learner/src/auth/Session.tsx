import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Me, SessionOut } from "../api/types";

interface Stored { token: string; person: Me; active_at: number }

interface State {
  person: Me | null;
  signInWithPin: (code: string, pin: string) => Promise<void>;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

const Ctx = createContext<State | null>(null);
const KEY = "lms.learner.session";
// how often the app checks whether it has been left alone too long
const CHECK_EVERY_MS = 15_000;

function idleTooLong(s: Stored, now = Date.now()): boolean {
  return now - s.active_at > s.person.idle_seconds * 1000;
}

function read(): Stored | null {
  try {
    const s = JSON.parse(window.localStorage.getItem(KEY) ?? "null") as Stored | null;
    return s && !idleTooLong(s) ? s : null;
  } catch {
    return null;
  }
}

function write(s: Stored | null) {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch { /* private mode: signed in for this page only */ }
}

/** Who is signed in on this device. On a shared tablet the app forgets them
 * after the session's idle time (15 minutes for a PIN), as the API does, so
 * the next person never sees the last one's training. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Stored | null>(() => {
    const s = read();
    api.token = s?.token ?? null;
    return s;
  });

  const signOut = useCallback(() => {
    const token = api.token;
    api.token = null;
    write(null);
    setSession(null);
    // tell the API too; signed out here whatever it says
    if (token) void fetch("/v1/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.onSignedOut = signOut;
  }, [signOut]);

  useEffect(() => {
    if (!session) return;
    const touch = () => {
      const s = { ...session, active_at: Date.now() };
      write(s);
      session.active_at = s.active_at;
    };
    const check = setInterval(() => { if (idleTooLong(session)) signOut(); }, CHECK_EVERY_MS);
    window.addEventListener("pointerdown", touch);
    window.addEventListener("keydown", touch);
    return () => {
      clearInterval(check);
      window.removeEventListener("pointerdown", touch);
      window.removeEventListener("keydown", touch);
    };
  }, [session, signOut]);

  const signedIn = useCallback((out: SessionOut) => {
    const s = { token: out.token, person: out.person, active_at: Date.now() };
    api.token = s.token;
    write(s);
    setSession(s);
  }, []);

  const signInWithPin = useCallback(async (code: string, pin: string) => {
    signedIn(await api.post<SessionOut>("/v1/auth/pin-login", { code, pin }));
  }, [signedIn]);

  const signInWithPassword = useCallback(async (email: string, password: string) => {
    signedIn(await api.post<SessionOut>("/v1/auth/login", { email, password }));
  }, [signedIn]);

  const value = useMemo<State>(() => ({ person: session?.person ?? null, signInWithPin, signInWithPassword, signOut }),
                               [session, signInWithPin, signInWithPassword, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): State {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
