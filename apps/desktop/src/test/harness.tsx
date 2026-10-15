import { render } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { Me, Settings } from "../api/types";

export function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export const MEL: Me = {
  id: 2, code: "MG001", name: "Mel Grant", email: "mel@example.com.au", permission: "manager", method: "password",
  scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read", "people:read",
           "people:write", "roles:write", "competencies:write", "records:write", "tickets:verify", "printing:write"],
  idle_seconds: 43200,
};

/** An admin: everything, Settings with its webhooks and API keys too. */
export const ADA: Me = { ...MEL, id: 1, code: "AD001", name: "Ada Admin", email: "ada@example.com.au",
                         permission: "admin", scopes: ["*"] };

/** GET /v1/settings as a fresh install answers it. */
export const ALL_SETTINGS: Settings = {
  sign_in_pin: { value: true, source: "default" },
  sign_in_password: { value: true, source: "default" },
  sign_in_entra: { value: true, source: "default", set_up: false },
  quiz_cooldown_tries: { value: 3, source: "default" },
  quiz_cooldown_minutes: { value: 60, source: "default" },
  reminder_days: { value: [30, 14, 0], source: "default" },
  timezone: { value: "Australia/Melbourne", source: "default" },
  daily_hour: { value: 6, source: "default" },
  smtp_host: { value: "", source: "default" },
  smtp_port: { value: 587, source: "default" },
  smtp_user: { value: "", source: "default" },
  smtp_password: { set: false, source: "default" },
  smtp_from: { value: "", source: "default" },
  smtp_security: { value: "starttls", source: "default" },
  public_url: { value: "", source: "default" },
  upload_files_per_day: { value: 30, source: "default" },
  upload_mb_per_day: { value: 200, source: "default" },
  platen_url: { value: "", source: "default" },
  platen_key: { set: false, source: "default" },
  certificate_printer: { value: "office", source: "default" },
  skills_card_printer: { value: "", source: "default" },
};

export interface Call { method: string; url: string; body: unknown; contentType?: string }
type Handler = (method: string, url: string, body: unknown) => Response | null | Promise<Response | null>;

/** An XMLHttpRequest as far as the client uses one: a test answers it, says
 * how far it has got, fails it, or sees it aborted. */
export class FakeXhr {
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: unknown = undefined;
  aborted = false;
  status = 0;
  responseText = "";
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(body: unknown) { this.body = body; }
  abort() { this.aborted = true; this.onabort?.(); }
  answer(status: number, text: string) {
    if (this.aborted) return;
    this.status = status;
    this.responseText = text;
    this.onload?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent);
  }
  fail() { this.onerror?.(); }
}

/** Signed in as `me` (Mel, a manager); `more` answers everything else, or it is a 404. */
export function stubApi(more: Handler = () => null, me: Me = MEL) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    // JSON is read back; a file (a Blob) is kept as it was sent
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body ?? undefined;
    calls.push({ method, url, body, contentType: (init.headers as Record<string, string> | undefined)?.["Content-Type"] });
    if (url === "/v1/auth/me") return json(200, me);
    if (url === "/v1/auth/logout") return new Response(null, { status: 204 });
    const answer = await more(method, url, body);
    return answer ?? json(404, { detail: `no stub for ${method} ${url}` });
  });
  vi.stubGlobal("fetch", fetchMock);
  // a file goes by XMLHttpRequest, for its progress: answered the same way
  const sending: FakeXhr[] = [];
  vi.stubGlobal("XMLHttpRequest", class extends FakeXhr {
    constructor() { super(); sending.push(this); }
    send(body: unknown) {
      super.send(body);
      void fetchMock(this.url, { method: this.method, headers: this.headers, body: body as BodyInit })
        .then(async (res) => this.answer(res.status, await res.text()), () => this.fail());
    }
  });
  return { calls, fetchMock, sending };
}

function Where() {
  const { pathname, search } = useLocation();
  return <><output data-testid="where">{pathname}</output><output data-testid="search">{search}</output></>;
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
