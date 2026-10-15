/** What the API answers: docs/api.md. */

export type Permission = "learner" | "supervisor" | "manager" | "admin";
export type Kind = "module" | "practical" | "ticket" | "policy";
export type Status = "current" | "expiring" | "lapsed" | "missing" | "waived" | "not_required";

export interface Me {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: Permission;
  method: "password" | "pin";
  scopes: string[];
  idle_seconds: number;
}

export interface SessionOut { token: string; person: Me }
export interface Page<T> { items: T[]; total: number }
export interface PersonRef { code: string; name: string }
export interface RoleRef { key: string; name: string }
export interface CompetencyRef { key: string; name: string; kind: Kind }

export interface Person {
  id: number;
  code: string;
  name: string;
  email: string | null;
  permission: Permission;
  supervisor: PersonRef | null;
  roles: RoleRef[];
  active: boolean;
  has_pin: boolean;
  pin_locked: boolean;
  has_password: boolean;
}

export interface Role {
  id: number;
  key: string;
  name: string;
  competencies: CompetencyRef[];
  people: number;
}

export interface Competency {
  id: number;
  key: string;
  name: string;
  kind: Kind;
  refresher_months: number | null;
  /** a ticket: whether its card has an expiry date to type in */
  card_expires: boolean;
  active: boolean;
}

export interface Cell { status: Status; granted_on: string | null; expires_on: string | null }

export interface MatrixRow {
  code: string;
  name: string;
  roles: RoleRef[];
  supervisor: PersonRef | null;
  cells: Record<string, Cell>;
}

export interface Matrix { today: string; competencies: CompetencyRef[]; people: MatrixRow[] }

export interface Override {
  id: number;
  competency: CompetencyRef;
  kind: "extra" | "waive";
  note: string;
  recorded_by: PersonRef;
  created_at: string;
}

export interface CompetencyRecord {
  id: number;
  competency: CompetencyRef;
  kind: "granted" | "revoked";
  granted_on: string | null;
  expires_on: string | null;
  note: string | null;
  recorded_by: PersonRef;
  /** a policy: the version this grant is for */
  policy_version: number | null;
  /** signed in the learner app: the name typed, and the signature's upload id */
  signed_name: string | null;
  signature: string | null;
  /** a ticket a manager checked: its submission's id */
  ticket: number | null;
  created_at: string;
}

export interface PolicyVersion {
  id: number;
  version: number;
  body: string;
  note: string | null;
  published_by: PersonRef;
  created_at: string;
}

export interface Ticket {
  id: number;
  person: PersonRef;
  competency: CompetencyRef;
  number: string;
  expires_on: string | null;
  /** upload ids: GET /v1/uploads/{id} */
  front: string;
  back: string | null;
  status: "pending" | "approved" | "rejected";
  reason: string | null;
  decided_by: PersonRef | null;
  decided_at: string | null;
  created_at: string;
}
export interface Upload { id: string; purpose: string; content_type: string; size_bytes: number; created_at: string }
