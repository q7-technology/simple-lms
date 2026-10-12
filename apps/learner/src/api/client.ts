/** The learner app is an ordinary API client with a session token, however
 * the person signed in. Nothing here a partner could not do (rule 4). */

export class ApiError extends Error {
  status: number;
  /** The API's reason when it gives one: wrong_pin, wrong_password, locked, ... */
  code: string | null;
  constructor(status: number, body: unknown) {
    const detail = (body as { detail?: unknown })?.detail;
    super(typeof detail === "string" ? detail : `Simple LMS answered ${status}`);
    this.status = status;
    const code = (body as { code?: unknown })?.code;
    this.code = typeof code === "string" ? code : null;
  }
}

/** No signal, or no proper answer. */
export class Unreachable extends Error {
  constructor() {
    super("No signal: Simple LMS can't be reached right now.");
  }
}

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
const SIGN_INS = new Set(["/v1/auth/login", "/v1/auth/pin-login"]);

export class LearnerApi {
  token: string | null = null;
  /** The API no longer takes the token: idle too long, or the PIN changed. */
  onSignedOut: (() => void) | null = null;
  private fetcher: Fetcher;

  constructor(fetcher?: Fetcher) {
    this.fetcher = fetcher ?? ((url, init) => fetch(url, init));
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      throw new Unreachable();
    }
    if (res.status === 401 && !SIGN_INS.has(path)) this.onSignedOut?.();
    if (res.status === 204) return undefined as T;
    let parsed: unknown;
    try {
      const text = await res.text();
      parsed = text ? JSON.parse(text) : null;
    } catch {
      throw new Unreachable();
    }
    if (!res.ok) throw new ApiError(res.status, parsed);
    return parsed as T;
  }

  get<T>(path: string) { return this.request<T>("GET", path); }
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
}

export const api = new LearnerApi();
