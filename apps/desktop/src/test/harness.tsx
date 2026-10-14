import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { Me } from "../api/types";

export function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const MEL: Me = {
  id: 2, code: "MG001", name: "Mel Grant", email: "mel@example.com.au", permission: "manager", method: "password",
  scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read", "people:read",
           "people:write", "roles:write", "competencies:write", "records:write", "tickets:verify"],
  idle_seconds: 43200,
};

export interface Call { method: string; url: string; body: unknown }
type Handler = (method: string, url: string, body: unknown) => Response | null | Promise<Response | null>;

/** Signed in as `me` (Mel, a manager); `more` answers everything else, or it is a 404. */
export function stubApi(more: Handler = () => null, me: Me = MEL) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(init.body as string) : undefined;
    calls.push({ method, url, body });
    if (url === "/v1/auth/me") return json(200, me);
    if (url === "/v1/auth/logout") return new Response(null, { status: 204 });
    const answer = await more(method, url, body);
    return answer ?? json(404, { detail: `no stub for ${method} ${url}` });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

export function renderApp(path: string, signedIn = true) {
  api.token = signedIn ? "lms_s.test" : null;
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppRoutes />
        <Where />
      </AuthProvider>
    </MemoryRouter>,
  );
}
