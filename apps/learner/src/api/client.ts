import type { Upload } from "./types";

/** The learner app is an ordinary API client with a session token, however
 * the person signed in. Nothing here a partner could not do (rule 4). */

export class ApiError extends Error {
  status: number;
  /** The API's reason when it gives one: wrong_pin, wrong_password, locked, ... */
  code: string | null;
  /** What a field needs, when the API says (a 422) */
  errors: { field: string; message: string }[];
  /** Whether the API gave a reason of its own (a detail or field errors), not
   * just a status */
  hasDetail: boolean;
  /** The API's answer as it came, for anything more it says (a retry_at, say) */
  body: unknown;
  constructor(status: number, body: unknown) {
    const detail = (body as { detail?: unknown })?.detail;
    const errors = (body as { errors?: { field: string; message: string }[] })?.errors ?? [];
    super(typeof detail === "string" ? detail
      : errors.length > 0 ? errors.map((e) => e.message).join("; ") : `Simple LMS answered ${status}`);
    this.status = status;
    this.body = body;
    this.errors = errors;
    this.hasDetail = typeof detail === "string" || errors.length > 0;
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
const SIGN_INS = new Set(["/v1/auth/login", "/v1/auth/pin-login", "/v1/auth/entra/finish"]);

export class LearnerApi {
  token: string | null = null;
  /** The API no longer takes the token: idle too long, or the PIN changed. */
  onSignedOut: (() => void) | null = null;
  private fetcher: Fetcher;

  constructor(fetcher?: Fetcher) {
    this.fetcher = fetcher ?? ((url, init) => fetch(url, init));
  }

  /** JSON, or a file (a Blob) sent as it is. */
  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const file = body instanceof Blob ? body : null;
    if (body !== undefined) headers["Content-Type"] = file ? file.type || "application/octet-stream" : "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : file ?? JSON.stringify(body) });
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
  put<T>(path: string, body: unknown) { return this.request<T>("PUT", path, body); }
  /** A ticket's photo or a signature, kept by the API before what names it. */
  upload(purpose: "ticket" | "signature", file: Blob) {
    return this.request<Upload>("POST", `/v1/uploads?purpose=${purpose}`, file);
  }
}

export const api = new LearnerApi();
