import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Me, SessionOut } from "../api/types";

export const LEARNERS_ELSEWHERE =
  "The desktop is for supervisors, managers and admins. Your training is in the learner app at /learn/.";

interface AuthState {
  ready: boolean;
  me: Me | null;
  /** Why the session could not be checked, when it is kept to try again. */
  trouble: string | null;
  retry: () => void;
  signIn: (email: string, password: string) => Promise<void>;
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

  const signIn = useCallback(async (email: string, password: string) => {
    const out = await api.post<SessionOut>("/v1/auth/login", { email, password });
    api.token = out.token;
    if (out.person.permission === "learner") {
      await api.post("/v1/auth/logout").catch(() => undefined);
      api.token = null;
      throw new Error(LEARNERS_ELSEWHERE);
    }
    setMe(out.person);
  }, []);

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

  const value = useMemo(() => ({ ready, me, trouble, retry, signIn, signOut, can }),
                        [ready, me, trouble, retry, signIn, signOut, can]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
