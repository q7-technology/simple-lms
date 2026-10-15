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
  /** a ticket: whether its card has an expiry date to type in (null otherwise) */
  card_expires: boolean | null;
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
  /** a module passed in the learner app: the version, the score and the pass mark */
  quiz: { version: number; score: number; pass_mark: number } | null;
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

export type PageKind = "text" | "image" | "pdf" | "video" | "link";

export interface ModulePage {
  kind: PageKind;
  title: string;
  body: string | null;
  url: string | null;
  /** a picture, PDF or video; `link` opens it without the token, for a few hours */
  file: { id: string; content_type: string; size_bytes: number; link: string } | null;
}

export interface Question { prompt: string; options: string[]; correct: number }

export interface ModuleVersion {
  id: number;
  version: number;
  pass_mark: number;
  /** null while it is a draft */
  published_at: string | null;
  published_by: PersonRef | null;
  pages: ModulePage[];
  questions: Question[];
  created_at: string;
  /** changed by every save: sent back as `based_on`, so a save meanwhile isn't undone */
  saved_at: string;
}

/** Where a setting's value comes from: set on the Settings screen, .env, or the default. */
export type SettingSource = "here" | "env" | "default";
export interface SettingValue<T> { value: T; source: SettingSource }

export interface Settings {
  sign_in_pin: SettingValue<boolean>;
  sign_in_password: SettingValue<boolean>;
  quiz_cooldown_tries: SettingValue<number>;
  quiz_cooldown_minutes: SettingValue<number>;
  reminder_days: SettingValue<number[]>;
  timezone: SettingValue<string>;
  daily_hour: SettingValue<number>;
  smtp_host: SettingValue<string>;
  smtp_port: SettingValue<number>;
  smtp_user: SettingValue<string>;
  /** never sent back: only whether there is one */
  smtp_password: { set: boolean; source: SettingSource };
  smtp_from: SettingValue<string>;
  smtp_security: SettingValue<"starttls" | "ssl" | "none">;
  public_url: SettingValue<string>;
}

/** A practical's checklist: the items a supervisor ticks, frozen once published. */
export interface Checklist {
  id: number;
  version: number;
  items: { id: number; text: string }[];
  note: string | null;
  published_by: PersonRef;
  created_at: string;
}
