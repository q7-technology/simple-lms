/** What the API answers: docs/api.md. */

export type Status = "current" | "expiring" | "lapsed" | "missing";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: string;
  method: "password" | "pin" | "entra";
  scopes: string[];
  idle_seconds: number;
}

export interface SessionOut { token: string; person: Me }
/** The ways of signing in that are on: Microsoft only once it is set up. */
export interface SignInMethods { pin: boolean; password: boolean; entra: boolean }

export interface TrainingItem {
  key: string;
  name: string;
  kind: "module" | "practical" | "ticket" | "policy";
  status: Status;
  granted_on: string | null;
  expires_on: string | null;
  /** a ticket: whether its card has an expiry date to type in (null otherwise) */
  card_expires: boolean | null;
  /** a ticket sent in and waiting for a manager's check */
  waiting: boolean;
}

export interface Training {
  person: { code: string; name: string };
  today: string;
  items: TrainingItem[];
}

export interface Policy {
  key: string;
  name: string;
  version: { id: number; version: number; body: string; note: string | null; created_at: string };
}

export interface Upload { id: string; purpose: string; content_type: string; size_bytes: number; created_at: string }

export interface Ticket {
  id: number;
  competency: { key: string; name: string; kind: string };
  number: string;
  expires_on: string | null;
  status: "pending" | "approved" | "rejected";
  reason: string | null;
  created_at: string;
}

export interface ModulePage {
  kind: "text" | "image" | "pdf" | "video" | "link";
  title: string;
  body: string | null;
  url: string | null;
  /** a picture, PDF or video: `link` opens it without the token, for a few hours */
  file: { id: string; content_type: string; size_bytes: number; link: string } | null;
}

export interface Module {
  key: string;
  name: string;
  version: {
    id: number;
    version: number;
    pass_mark: number;
    pages: ModulePage[];
    /** never which answer is right: the API marks it */
    questions: { prompt: string; options: string[] }[];
  };
  /** the page to open at; one past the last is the quiz */
  resume_at: number;
  /** after too many goes in a row that didn't pass, when they may try again; null: now */
  retry_at: string | null;
  /** the same, ready to show in the business's time zone: "2:15 pm" */
  retry_at_text: string | null;
}

export interface Attempt {
  id: number;
  version: number;
  correct: number;
  total: number;
  score: number;
  pass_mark: number;
  passed: boolean;
  created_at: string;
  /** when the next go may be, if this attempt started a wait (as Module's) */
  retry_at: string | null;
  retry_at_text: string | null;
}

/** Someone the caller may sign off, and the practicals they are asked for. */
export interface SignsOff {
  code: string;
  name: string;
  practicals: { key: string; name: string; status: Status; expires_on: string | null }[];
}

/** A practical and the checklist to tick now. */
export interface Practical {
  key: string;
  name: string;
  version: { id: number; version: number; note: string | null; items: { id: number; text: string }[] };
}
