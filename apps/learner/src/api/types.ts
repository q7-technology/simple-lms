/** What the API answers: docs/api.md. */

export type Status = "current" | "expiring" | "lapsed" | "missing";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: string;
  method: "password" | "pin";
  scopes: string[];
  idle_seconds: number;
}

export interface SessionOut { token: string; person: Me }

export interface TrainingItem {
  key: string;
  name: string;
  kind: "module" | "practical" | "ticket" | "policy";
  status: Status;
  granted_on: string | null;
  expires_on: string | null;
  /** a ticket: whether its card has an expiry date to type in */
  card_expires: boolean;
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
