import type { Upload } from "./types";

/** The desktop is an ordinary API client with a session token. Nothing here
 * a partner could not do with the same API (rule 4). */

export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  errors: FieldError[];
  /** The API's reason when it gives one: wrong_password, locked, own_record, ... */
  code: string | null;
  constructor(status: number, body: unknown) {
    const errors = ((body as { errors?: FieldError[] })?.errors ?? []) as FieldError[];
    const detail = (body as { detail?: unknown })?.detail;
    super(errors.length > 0 ? errors.map((e) => `${e.field}: ${e.message}`).join("; ")
      : typeof detail === "string" ? detail : `Simple LMS answered ${status}`);
    this.status = status;
    this.errors = errors;
    const code = (body as { code?: unknown })?.code;
    this.code = typeof code === "string" ? code : null;
  }
}

/** The API could not be reached, or did not answer properly. */
export class Unreachable extends Error {
  constructor() {
    super("Can't reach Simple LMS right now.");
  }
}

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
type Params = Record<string, string | number | boolean | null | undefined>;

const TOKEN_KEY = "lms.desktop.token";
const TOO_BIG = "That file is too big: the most is 200 MB for a video, 20 MB otherwise.";

function query(params?: Params): string {
  if (!params) return "";
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `?${qs}` : "";
}

export class ApiClient {
  /** Called when the API stops taking the token: idle too long, or signed out elsewhere. */
  onSignedOut: (() => void) | null = null;
  private fetcher: Fetcher;

  constructor(fetcher?: Fetcher) {
    this.fetcher = fetcher ?? ((url, init) => fetch(url, init));
  }

  get token(): string | null {
    try { return window.localStorage.getItem(TOKEN_KEY); } catch { return null; }
  }

  set token(value: string | null) {
    try {
      if (value) window.localStorage.setItem(TOKEN_KEY, value);
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch { /* private mode: signed in for this page only */ }
  }

  /** JSON, or a file (a Blob) sent as it is. */
  private async send(method: string, path: string, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json" };
    const file = body instanceof Blob ? body : null;
    if (body !== undefined) headers["Content-Type"] = file ? file.type || "application/octet-stream" : "application/json";
    const token = this.token;
    if (token) headers.Authorization = `Bearer ${token}`;
    let res: Response;
    try {
      res = await this.fetcher(path, { method, headers, body: body === undefined ? undefined : file ?? JSON.stringify(body) });
    } catch {
      throw new Unreachable();
    }
    if (res.status === 401 && token && !path.startsWith("/v1/auth/login")) {
      this.token = null;
      this.onSignedOut?.();
    }
    return res;
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.send(method, path, body);
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    let parsed: unknown;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      // Caddy refusing a body too big before the API sees it: say so plainly
      if (res.status === 413) throw new ApiError(413, { detail: TOO_BIG, code: "too_large" });
      // a proxy's error page, say: not the API's own answer
      throw new Unreachable();
    }
    if (!res.ok) throw new ApiError(res.status, parsed);
    return parsed as T;
  }

  get<T>(path: string, params?: Params) { return this.request<T>("GET", path + query(params)); }
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
  patch<T>(path: string, body: unknown) { return this.request<T>("PATCH", path, body); }
  put<T>(path: string, body: unknown) { return this.request<T>("PUT", path, body); }

  /** A module page's picture, PDF or video, kept by the API before the
   * page that shows it is saved. What counts is its first bytes. */
  upload(purpose: "page-image" | "page-pdf" | "page-video", file: Blob) {
    return this.request<Upload>("POST", `/v1/uploads?purpose=${purpose}`, file);
  }

  /** A file kept by the API (a ticket's photo, a signature), fetched with the
   * session's token: an <img> can't send it. */
  async blob(path: string): Promise<Blob> {
    const res = await this.send("GET", path);
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    return res.blob();
  }

  /** A file the API makes (the matrix as CSV), saved by the browser. */
  async download(path: string, params: Params, filename: string): Promise<void> {
    const res = await this.send("GET", path + query(params));
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }
}

export const api = new ApiClient();
