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
  created_at: string;
}
