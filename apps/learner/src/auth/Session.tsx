import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Me, SessionOut } from "../api/types";

interface Stored { token: string; person: Me; active_at: number }

/** Leaving for Microsoft's sign-in page; a test stands in for it. */
export const browser = { go: (url: string) => window.location.assign(url) };

// the secret this tab keeps while the person is at Microsoft (POST /v1/auth/entra/start)
const ENTRA_KEY = "lms.learner.entra";

function tabSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface State {
  person: Me | null;
  signInWithPin: (code: string, pin: string) => Promise<void>;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  /** Off to Microsoft's sign-in page; it sends the person back to /learn/sign-in. */
  startEntra: () => Promise<void>;
  /** Back from Microsoft with a hand-off code: a session, as from a PIN. */
  finishEntra: (code: string) => Promise<void>;
  signOut: () => void;
  /** Someone is here though nobody taps: a video playing. Counts as a tap,
   * here and at the API, unless the idle time has passed already. */
  stillHere: () => void;
}

const Ctx = createContext<State | null>(null);
const KEY = "lms.learner.session";
// how often the app checks whether it has been left alone too long
const CHECK_EVERY_MS = 15_000;

function idleTooLong(s: Stored, now = Date.now()): boolean {
  return now - s.active_at > s.person.idle_seconds * 1000;
}


function write(s: Stored | null) {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch { /* private mode: signed in for this page only */ }
}

function logout(token: string) {
  // tell the API too; signed out here whatever it says
  void fetch("/v1/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => undefined);
}

/** What the device holds, as it is. */
function peek(): Stored | null {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "null") as Stored | null;
  } catch {
    return null;
  }
}

/** Who is on this device, if they have not left it alone too long. A session
 * left idle is wiped from the device, token and all, not just ignored. */
function read(): Stored | null {
  const s = peek();
  if (s && !idleTooLong(s)) return s;
  write(null);
  if (s?.token) logout(s.token);
  return null;
}

/** Who is signed in on this device. On a shared tablet the app forgets them
 * after the session's idle time (15 minutes for a PIN or Microsoft), as the API does, so
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
    if (token) logout(token);
  }, []);

  useEffect(() => {
    api.onSignedOut = signOut;
  }, [signOut]);

  // the last tap in any tab on this device: they share one session
  const activeAt = useRef(session?.active_at ?? 0);
  // what a tap does, for stillHere()
  const tapped = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!session) return;
    activeAt.current = session.active_at;
    const check = () => {
      const shared = peek();
      if (shared?.token === session.token) activeAt.current = Math.max(activeAt.current, shared.active_at);
      if (!idleTooLong({ ...session, active_at: activeAt.current })) return false;
      signOut();
      return true;
    };
    // a tap after the idle time is the next person: it signs out, never extends
    const touch = () => {
      if (check()) return;
      activeAt.current = Date.now();
      write({ ...session, active_at: activeAt.current });
    };
    // another tab signed out, or someone else signed in there: drop this one at once
    const elsewhere = (e: StorageEvent) => {
      if (e.key !== KEY && e.key !== null) return;
      const shared = peek();
      if (shared?.token === session.token) {
        activeAt.current = Math.max(activeAt.current, shared.active_at);
        return;
      }
      api.token = shared?.token ?? null;
      setSession(shared && !idleTooLong(shared) ? shared : null);
    };
    // timers stop while a tablet sleeps, so check again the moment it wakes
    const woke = () => { if (document.visibilityState === "visible") check(); };
    tapped.current = touch;
    const every = setInterval(check, CHECK_EVERY_MS);
    window.addEventListener("pointerdown", touch, true);
    window.addEventListener("keydown", touch, true);
    window.addEventListener("focus", woke);
    window.addEventListener("pageshow", woke);
    document.addEventListener("visibilitychange", woke);
    window.addEventListener("storage", elsewhere);
    return () => {
      tapped.current = () => undefined;
      window.removeEventListener("storage", elsewhere);
      clearInterval(every);
      window.removeEventListener("pointerdown", touch, true);
      window.removeEventListener("keydown", touch, true);
      window.removeEventListener("focus", woke);
      window.removeEventListener("pageshow", woke);
      document.removeEventListener("visibilitychange", woke);
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

  const startEntra = useCallback(async () => {
    const verifier = tabSecret();
    const out = await api.post<{ url: string }>("/v1/auth/entra/start", { app: "learner", verifier });
    try { window.sessionStorage.setItem(ENTRA_KEY, verifier); } catch { /* private mode: finishing says it expired */ }
    browser.go(out.url);
  }, []);

  const finishEntra = useCallback(async (code: string) => {
    let verifier = "";
    try {
      verifier = window.sessionStorage.getItem(ENTRA_KEY) ?? "";
      window.sessionStorage.removeItem(ENTRA_KEY);
    } catch { /* private mode */ }
    signedIn(await api.post<SessionOut>("/v1/auth/entra/finish", { code, verifier }));
  }, [signedIn]);

  const stillHere = useCallback(() => {
    tapped.current();
    // the API counts idle time too: any request tells it someone is here
    if (api.token) void api.get("/v1/auth/me").catch(() => undefined);
  }, []);

  const value = useMemo<State>(() => ({ person: session?.person ?? null, signInWithPin, signInWithPassword, startEntra,
                                        finishEntra, signOut, stillHere }),
                               [session, signInWithPin, signInWithPassword, startEntra, finishEntra, signOut, stillHere]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): State {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
