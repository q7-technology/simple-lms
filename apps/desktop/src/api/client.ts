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

/** A file stopped on purpose (Cancel), not lost on the way. */
export class Cancelled extends Error {
  constructor() {
    super("Stopped sending it.");
  }
}

/** A file on its way: settles as the upload does; abort() stops it. */
export type Sending<T> = Promise<T> & { abort: () => void };

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

/** The API's answer as JSON, or why there isn't one. */
function answer<T>(status: number, text: string): T {
  let parsed: unknown;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    // Caddy refusing a body too big before the API sees it: say so plainly
    if (status === 413) throw new ApiError(413, { detail: TOO_BIG, code: "too_large" });
    // a proxy's error page, say: not the API's own answer
    throw new Unreachable();
  }
  if (status < 200 || status >= 300) throw new ApiError(status, parsed);
  return parsed as T;
}

export class ApiClient {
  /** Called when the API stops taking the token: idle too long, or signed out elsewhere. */
  onSignedOut: (() => void) | null = null;
  private fetcher: Fetcher;
  private xhr: () => XMLHttpRequest;

  constructor(fetcher?: Fetcher, xhr?: () => XMLHttpRequest) {
    this.fetcher = fetcher ?? ((url, init) => fetch(url, init));
    this.xhr = xhr ?? (() => new XMLHttpRequest());
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
    this.signedOutIf(res.status, token, path);
    return res;
  }

  private signedOutIf(status: number, token: string | null, path: string) {
    if (status === 401 && token && !path.startsWith("/v1/auth/login")) {
      this.token = null;
      this.onSignedOut?.();
    }
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.send(method, path, body);
    if (res.status === 204) return undefined as T;
    return answer<T>(res.status, await res.text());
  }

  get<T>(path: string, params?: Params) { return this.request<T>("GET", path + query(params)); }
  post<T>(path: string, body: unknown = {}) { return this.request<T>("POST", path, body); }
  patch<T>(path: string, body: unknown) { return this.request<T>("PATCH", path, body); }
  put<T>(path: string, body: unknown) { return this.request<T>("PUT", path, body); }

  /** A module page's picture, PDF or video, kept by the API before the
   * page that shows it is saved. What counts is its first bytes. Sent by
   * XMLHttpRequest, as fetch can't say how far a file has got: `onProgress`
   * hears the part sent so far, 0 to 1. */
  upload(purpose: "page-image" | "page-pdf" | "page-video", file: Blob,
         onProgress?: (done: number) => void): Sending<Upload> {
    const path = `/v1/uploads?purpose=${purpose}`;
    const xhr = this.xhr();
    const sending = new Promise<Upload>((resolve, reject) => {
      xhr.open("POST", path);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
      const token = this.token;
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && e.total > 0) onProgress?.(e.loaded / e.total); };
      xhr.onload = () => {
        this.signedOutIf(xhr.status, token, path);
        try { resolve(answer<Upload>(xhr.status, xhr.responseText)); } catch (e) { reject(e); }
      };
      xhr.onerror = () => reject(new Unreachable());
      xhr.onabort = () => reject(new Cancelled());
      xhr.send(file);
    });
    return Object.assign(sending, { abort: () => xhr.abort() });
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
