import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes } from "../App";
import { SessionProvider } from "../auth/Session";
import type { Me } from "../api/types";

export function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const KIM: Me = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", method: "pin",
  scopes: ["training:read"], idle_seconds: 900,
};

export interface Call { method: string; url: string; body: unknown }
type Handler = (method: string, url: string, body: unknown) => Response | null;

export function stubApi(more: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method, url, body });
    return more(method, url, body) ?? json(404, { detail: `no stub for ${method} ${url}` });
  }));
  return calls;
}

/** Signed in already when `who` is given, as if the app had been opened again. */
export function renderApp(who: Me | null = null, activeAt = Date.now()) {
  if (who) window.localStorage.setItem("lms.learner.session", JSON.stringify({ token: "lms_s.kim", person: who, active_at: activeAt }));
  return render(
    <MemoryRouter>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
}
