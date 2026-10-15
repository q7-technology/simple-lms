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

export interface Call { method: string; url: string; body: unknown; contentType?: string }
type Handler = (method: string, url: string, body: unknown) => Response | null;

export function stubApi(more: Handler) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    // JSON is read back; a file (a Blob) is kept as it was sent
    const body = typeof init.body === "string" ? JSON.parse(init.body) : init.body ?? undefined;
    calls.push({ method, url, body, contentType: (init.headers as Record<string, string> | undefined)?.["Content-Type"] });
    return more(method, url, body) ?? json(404, { detail: `no stub for ${method} ${url}` });
  }));
  return calls;
}

/** Signed in already when `who` is given, as if the app had been opened again,
 * at `path` (My training unless told). */
export function renderApp(who: Me | null = null, activeAt = Date.now(), path = "/") {
  if (who) window.localStorage.setItem("lms.learner.session", JSON.stringify({ token: "lms_s.kim", person: who, active_at: activeAt }));
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </MemoryRouter>,
  );
}

/** An AudioContext that counts the notes it is asked to play. */
export function listen() {
  const heard = { notes: 0, woken: 0 };
  class FakeAudioContext {
    state = "suspended";
    currentTime = 0;
    destination = {};
    resume() { heard.woken += 1; this.state = "running"; return Promise.resolve(); }
    createOscillator() {
      return { type: "", frequency: { setValueAtTime() {} }, connect: (n: unknown) => n, start() { heard.notes += 1; }, stop() {} };
    }
    createGain() {
      return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (n: unknown) => n };
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return heard;
}
