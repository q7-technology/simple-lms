import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Me, SessionOut } from "../api/types";

export const LEARNERS_ELSEWHERE =
  "The desktop is for supervisors, managers and admins. Your training is in the learner app at /learn/.";

/** Leaving for Microsoft's sign-in page; a test stands in for it. */
export const browser = { go: (url: string) => window.location.assign(url) };

// the secret this tab keeps while the person is at Microsoft (POST /v1/auth/entra/start)
const ENTRA_KEY = "lms.desktop.entra";

function tabSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface AuthState {
  ready: boolean;
  me: Me | null;
  /** Why the session could not be checked, when it is kept to try again. */
  trouble: string | null;
  retry: () => void;
  signIn: (email: string, password: string) => Promise<void>;
  /** Off to Microsoft's sign-in page; it sends the person back to /sign-in. */
  startEntra: () => Promise<void>;
  /** Back from Microsoft with a hand-off code: a session, as from a password. */
  finishEntra: (code: string) => Promise<void>;
  signOut: () => Promise<void>;
  can: (scope: string) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    api.onSignedOut = () => setMe(null);
    (async () => {
      try {
        if (api.token) setMe(await api.get<Me>("/v1/auth/me"));
        setTrouble(null);
      } catch (e) {
        // a refused token is already forgotten; anything else is worth another try
        setTrouble(e instanceof ApiError ? null : (e as Error).message);
      } finally {
        setReady(true);
      }
    })();
  }, [attempt]);

  const retry = useCallback(() => { setReady(false); setAttempt((n) => n + 1); }, []);

  /** Signed in, however: a learner is sent to the learner app instead. */
  const accept = useCallback(async (out: SessionOut) => {
    api.token = out.token;
    if (out.person.permission === "learner") {
      await api.post("/v1/auth/logout").catch(() => undefined);
      api.token = null;
      throw new Error(LEARNERS_ELSEWHERE);
    }
    setMe(out.person);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    await accept(await api.post<SessionOut>("/v1/auth/login", { email, password }));
  }, [accept]);

  const startEntra = useCallback(async () => {
    const verifier = tabSecret();
    const out = await api.post<{ url: string }>("/v1/auth/entra/start", { app: "desktop", verifier });
    try { window.sessionStorage.setItem(ENTRA_KEY, verifier); } catch { /* private mode: finishing says it expired */ }
    browser.go(out.url);
  }, []);

  const finishEntra = useCallback(async (code: string) => {
    let verifier = "";
    try {
      verifier = window.sessionStorage.getItem(ENTRA_KEY) ?? "";
      window.sessionStorage.removeItem(ENTRA_KEY);
    } catch { /* private mode */ }
    await accept(await api.post<SessionOut>("/v1/auth/entra/finish", { code, verifier }));
  }, [accept]);

  const signOut = useCallback(async () => {
    try {
      await api.post("/v1/auth/logout");
    } catch { /* signed out here whatever the API says */ }
    api.token = null;
    setMe(null);
  }, []);

  const can = useCallback((scope: string) => {
    if (!me) return false;
    const area = scope.split(":")[0];
    return me.scopes.includes("*") || me.scopes.includes(scope) || me.scopes.includes(`${area}:*`);
  }, [me]);

  const value = useMemo(() => ({ ready, me, trouble, retry, signIn, startEntra, finishEntra, signOut, can }),
                        [ready, me, trouble, retry, signIn, startEntra, finishEntra, signOut, can]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
