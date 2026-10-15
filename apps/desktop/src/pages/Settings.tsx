import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Me, Settings as All, SettingSource } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { Webhooks } from "./Webhooks";

type Key = keyof All;
type Kind = "bool" | "int" | "days" | "text" | "secret";
type Draft = Partial<Record<Key, string | boolean>>;

const KINDS: Record<Key, Kind> = {
  sign_in_pin: "bool", sign_in_password: "bool", sign_in_entra: "bool",
  quiz_cooldown_tries: "int", quiz_cooldown_minutes: "int",
  reminder_days: "days", timezone: "text", daily_hour: "int",
  smtp_host: "text", smtp_port: "int", smtp_user: "text", smtp_password: "secret",
  smtp_from: "text", smtp_security: "text", public_url: "text",
  upload_files_per_day: "int", upload_mb_per_day: "int",
};

const FROM: Record<SettingSource, string> = { here: "Set here", env: "From .env", default: "Default" };

const ZONES = ["Australia/Melbourne", "Australia/Sydney", "Australia/Brisbane", "Australia/Adelaide",
  "Australia/Darwin", "Australia/Perth", "Australia/Hobart", "Pacific/Auckland"];

/** An hour of the day as people say it: 6 am, 12 pm. */
const hour = (h: number) => `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;

function toDraft(all: All, key: Key): string | boolean {
  const s = all[key];
  if (!("value" in s)) return "";   // the password: never sent back
  const v = s.value;
  if (Array.isArray(v)) return v.join(", ");
  return typeof v === "boolean" ? v : String(v);
}

/** The draft as the API takes it, or why it can't be. */
function fromDraft(key: Key, draft: string | boolean): { value: unknown } | { problem: string } {
  const kind = KINDS[key];
  if (kind === "bool") return { value: draft };
  const text = String(draft).trim();
  if (kind === "int") return /^\d+$/.test(text) ? { value: Number(text) } : { problem: "A whole number, please." };
  if (kind === "days") {
    const parts = text.split(/[\s,]+/).filter(Boolean);
    if (parts.length === 0 || parts.some((p) => !/^\d+$/.test(p))) return { problem: "Whole days, e.g. 30, 14, 0." };
    return { value: parts.map(Number) };
  }
  return { value: kind === "secret" ? String(draft) : text };
}

/** A section of the settings: its own draft, saved on its own. */
function useSection(all: All, keys: Key[], onSaved: (all: All) => void) {
  const fresh = () => Object.fromEntries(keys.map((k) => [k, toDraft(all, k)])) as Draft;
  const [draft, setDraft] = useState<Draft>(fresh);
  const [errors, setErrors] = useState<Partial<Record<Key, string>>>({});
  const [said, setSaid] = useState<string | null>(null);
  const action = useAction();
  // saved here or elsewhere on the screen: this section's values only
  const mine = JSON.stringify(keys.map((k) => all[k]));
  useEffect(() => { setDraft(fresh()); }, [mine]);

  const set = (key: Key) => (value: string | boolean) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaid(null);
  };

  async function send(body: Record<string, unknown>, done: string) {
    setErrors({});
    setSaid(null);
    let out: All | null = null;
    const ok = await action.run(async () => {
      try {
        out = await api.put<All>("/v1/settings", body);
      } catch (e) {
        if (e instanceof ApiError && e.errors.length > 0) {
          setErrors(Object.fromEntries(e.errors.map((x) => [x.field.split(".")[0], x.message])));
          throw new Error("Not saved: see the field marked below.");
        }
        throw e;
      }
    });
    if (ok && out) {
      // a password goes once: never kept on the screen
      setDraft((d) => ({ ...d, ...Object.fromEntries(keys.filter((k) => KINDS[k] === "secret").map((k) => [k, ""])) }));
      onSaved(out);
      setSaid(done);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    const problems: Partial<Record<Key, string>> = {};
    for (const key of keys) {
      const d = draft[key];
      if (d === undefined) continue;
      if (KINDS[key] === "secret") { if (d !== "") body[key] = d; continue; }
      const out = fromDraft(key, d);
      if ("problem" in out) problems[key] = out.problem;
      else if (JSON.stringify(out.value) !== JSON.stringify((all[key] as { value: unknown }).value)) body[key] = out.value;
    }
    if (Object.keys(problems).length > 0) { setErrors(problems); setSaid(null); return; }
    if (Object.keys(body).length === 0) { setErrors({}); setSaid("Nothing has changed."); return; }
    await send(body, "Saved. It takes effect within a few seconds.");
  }

  const reset = (key: Key) => send({ [key]: null }, "Back to .env or the default.");
  return { draft, set, errors, said, action, save, reset, send };
}

/** A setting: its label, where its value comes from, and what's wrong with it. */
function Field({ label, hint, source, error, onReset, children }: {
  label: string; hint?: ReactNode; source: SettingSource; error?: string; onReset: () => void;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="label">{label}</label>
        <span className={`pill ${source === "here" ? "t-green" : "t-grey"}`}>{FROM[source]}</span>
        {source === "here" && (
          <button type="button" className="rowbtn small underline" onClick={onReset}>
            Use .env or the default<span className="sr"> for {label}</span></button>
        )}
      </div>
      {children(id)}
      {hint && <div className="small">{hint}</div>}
      {error && <div className="msg r">{error}</div>}
    </div>
  );
}

function Section({ title, sub, onSubmit, busy, error, said, extra, children }: {
  title: string; sub: ReactNode; onSubmit: (e: FormEvent) => void; busy: boolean; error: string | null;
  said: string | null; extra?: ReactNode; children: ReactNode;
}) {
  const heading = useId();
  return (
    <section className="card flex flex-col gap-3" aria-labelledby={heading} style={{ maxWidth: 720 }}>
      <div>
        <h2 id={heading} className="m-0 text-lg font-extrabold">{title}</h2>
        <div className="small">{sub}</div>
      </div>
      <form className="flex flex-col gap-3" onSubmit={onSubmit} noValidate>
        {children}
        <Problem error={error} />
        {said && <div className="msg g" role="status">{said}</div>}
        <div className="flex flex-wrap gap-3">
          <button type="submit" className="btn primary" disabled={busy}>Save</button>
          {extra}
        </div>
      </form>
    </section>
  );
}

/** Everyday settings, for an admin. What has to be known before Simple LMS
 * starts (the database, ports, the domain, the upload folder) stays in .env. */
export function Settings() {
  const { can } = useAuth();
  const loaded = useLoad(() => (can("settings:write") ? api.get<All>("/v1/settings") : Promise.resolve(null)), []);
  const [all, setAll] = useState<All | null>(null);
  useEffect(() => { if (loaded.data) setAll(loaded.data); }, [loaded.data]);

  if (!can("settings:write")) {
    return <main className="page"><h1>Settings</h1><p>Only an admin can change the settings.</p></main>;
  }
  return (
    <main className="page">
      <h1>Settings</h1>
      <p className="small m-0" style={{ maxWidth: 720 }}>
        Changes take effect within a few seconds, with no restart. Each value says where it comes from: set here,
        from <code>.env</code> on the server, or the default. A value set here wins over <code>.env</code>.
      </p>
      <Problem error={loaded.error} />
      {all && (
        <>
          <SignIn all={all} onSaved={setAll} />
          <Quizzes all={all} onSaved={setAll} />
          <Reminders all={all} onSaved={setAll} />
          <Email all={all} onSaved={setAll} />
          <WebAddress all={all} onSaved={setAll} />
          <Uploads all={all} onSaved={setAll} />
          <Webhooks />
        </>
      )}
    </main>
  );
}

interface Props { all: All; onSaved: (all: All) => void }

type Way = "sign_in_pin" | "sign_in_password" | "sign_in_entra";
const SIGNED_IN_WITH: Partial<Record<Me["method"], string>> = { password: "an email and password", entra: "Microsoft" };

function SignIn({ all, onSaved }: Props) {
  const { me } = useAuth();
  const s = useSection(all, ["sign_in_pin", "sign_in_password", "sign_in_entra"], onSaved);
  // the way this admin signed in stays on until they sign in another way (the API says so too)
  const mine: Way | null = me && me.method !== "pin" && all[`sign_in_${me.method}`].value ? `sign_in_${me.method}` : null;
  const box = (key: Way, label: string) => (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={s.draft[key] === true} disabled={key === mine}
             onChange={(e) => s.set(key)(e.target.checked)} />
      {label} <span className={`pill ${all[key].source === "here" ? "t-green" : "t-grey"}`}>{FROM[all[key].source]}</span>
    </label>
  );
  return (
    <Section title="Sign-in" sub="The ways people can sign in. Someone already signed in stays signed in until their session ends."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error} said={s.said}>
      {box("sign_in_pin", "Code and PIN (the learner app)")}
      {box("sign_in_password", "Email and password")}
      {box("sign_in_entra", "Microsoft")}
      {!all.sign_in_entra.set_up && (
        <div className="small">
          Microsoft isn't set up yet: it needs <code>LMS_ENTRA_TENANT_ID</code>, <code>LMS_ENTRA_CLIENT_ID</code> and{" "}
          <code>LMS_ENTRA_CLIENT_SECRET</code> in <code>.env</code> (see the README), and the web address below. Until then
          nobody sees its button.
        </div>
      )}
      {mine && me && (
        <div className="small">You signed in with {SIGNED_IN_WITH[me.method]}: to switch it off, sign in another way first.</div>
      )}
      <div className="small">
        Email and password or Microsoft stays on: one of them is the only way an admin can sign in, as a PIN never opens
        the desktop. The <code>lms</code> command on the server works whatever is switched off.
      </div>
    </Section>
  );
}

function Quizzes({ all, onSaved }: Props) {
  const s = useSection(all, ["quiz_cooldown_tries", "quiz_cooldown_minutes"], onSaved);
  return (
    <Section title="Quizzes" sub="After this many goes at a module's quiz in a row that didn't pass, the learner waits before the next."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error} said={s.said}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Failed tries in a row before the wait" hint="1 to 20" source={all.quiz_cooldown_tries.source}
               error={s.errors.quiz_cooldown_tries} onReset={() => void s.reset("quiz_cooldown_tries")}>
          {(id) => <input id={id} className="field" type="number" min={1} max={20} value={String(s.draft.quiz_cooldown_tries)}
                          onChange={(e) => s.set("quiz_cooldown_tries")(e.target.value)} />}
        </Field>
        <Field label="Wait, in minutes" hint="0 for no wait; 1440 is a day" source={all.quiz_cooldown_minutes.source}
               error={s.errors.quiz_cooldown_minutes} onReset={() => void s.reset("quiz_cooldown_minutes")}>
          {(id) => <input id={id} className="field" type="number" min={0} value={String(s.draft.quiz_cooldown_minutes)}
                          onChange={(e) => s.set("quiz_cooldown_minutes")(e.target.value)} />}
        </Field>
      </div>
    </Section>
  );
}

function Reminders({ all, onSaved }: Props) {
  const s = useSection(all, ["reminder_days", "daily_hour", "timezone"], onSaved);
  const zones = useId();
  return (
    <Section title="Reminders" sub="Each morning the daily job emails learners whose training is running out, and on Mondays sends managers a digest."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error} said={s.said}>
      <Field label="Reminder days" hint="Days before the last good day, e.g. 30, 14, 0 (0 is the day itself). 0 to 365."
             source={all.reminder_days.source} error={s.errors.reminder_days} onReset={() => void s.reset("reminder_days")}>
        {(id) => <input id={id} className="field" value={String(s.draft.reminder_days)}
                        onChange={(e) => s.set("reminder_days")(e.target.value)} />}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Daily job runs from" source={all.daily_hour.source} error={s.errors.daily_hour}
               onReset={() => void s.reset("daily_hour")}>
          {(id) => (
            <select id={id} className="field" value={String(s.draft.daily_hour)} onChange={(e) => s.set("daily_hour")(e.target.value)}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={String(h)}>{hour(h)}</option>)}
            </select>
          )}
        </Field>
        <Field label="Time zone" hint="Whose today decides what is current, and when the daily job runs"
               source={all.timezone.source} error={s.errors.timezone} onReset={() => void s.reset("timezone")}>
          {(id) => <input id={id} className="field" list={zones} value={String(s.draft.timezone)}
                          onChange={(e) => s.set("timezone")(e.target.value)} />}
        </Field>
        <datalist id={zones}>{ZONES.map((z) => <option key={z} value={z} />)}</datalist>
      </div>
    </Section>
  );
}

function Email({ all, onSaved }: Props) {
  const s = useSection(all, ["smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password", "smtp_from"], onSaved);
  const test = useAction();
  const [sent, setSent] = useState<string | null>(null);
  const text = (key: Key, label: string, hint?: string, type = "text") => (
    <Field label={label} hint={hint} source={all[key].source} error={s.errors[key]} onReset={() => void s.reset(key)}>
      {(id) => <input id={id} className="field" type={type} value={String(s.draft[key] ?? "")}
                      onChange={(e) => s.set(key)(e.target.value)} />}
    </Field>
  );

  async function sendTest() {
    setSent(null);
    let to = "";
    if (await test.run(async () => { to = (await api.post<{ to: string }>("/v1/settings/test-email")).to; })) {
      setSent(`Test email on its way to ${to}. It should arrive within a minute; if it doesn't, check the details here.`);
    }
  }

  return (
    <Section title="Email" sub="The mail server the reminders and digests go through. Until it has a host and a from address, emails wait."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error ?? test.error} said={s.said ?? sent}
             extra={<button type="button" className="btn" disabled={test.busy} onClick={() => void sendTest()}>Send a test email</button>}>
      <div className="grid grid-cols-2 gap-3">
        {text("smtp_host", "Host", "e.g. smtp.office365.com")}
        {text("smtp_port", "Port", "587 for STARTTLS, 465 for SSL", "number")}
      </div>
      <Field label="Security" source={all.smtp_security.source} error={s.errors.smtp_security}
             onReset={() => void s.reset("smtp_security")}>
        {(id) => (
          <select id={id} className="field" value={String(s.draft.smtp_security)} onChange={(e) => s.set("smtp_security")(e.target.value)}>
            <option value="starttls">STARTTLS (usually port 587)</option>
            <option value="ssl">SSL (usually port 465)</option>
            <option value="none">None (a relay on your own network)</option>
          </select>
        )}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        {text("smtp_user", "User", "Leave empty if the server doesn't ask")}
        <Field label="Password" source={all.smtp_password.source} error={s.errors.smtp_password}
               onReset={() => void s.reset("smtp_password")}
               hint={<>{all.smtp_password.set ? "A password is set. Leave this empty to keep it." : "No password set."}{" "}
                 {all.smtp_password.set && (
                   <button type="button" className="rowbtn underline" onClick={() => void s.send({ smtp_password: "" }, "Password cleared.")}>
                     Clear the password</button>
                 )}</>}>
          {(id) => <input id={id} className="field" type="password" autoComplete="new-password" value={String(s.draft.smtp_password ?? "")}
                          onChange={(e) => s.set("smtp_password")(e.target.value)} />}
        </Field>
      </div>
      {text("smtp_from", "From address", "e.g. Simple LMS <lms@yourcompany.com.au>")}
    </Section>
  );
}

function WebAddress({ all, onSaved }: Props) {
  const s = useSection(all, ["public_url"], onSaved);
  return (
    <Section title="Web address" sub="Where people open Simple LMS, for the links in emails and where Microsoft sends people back after signing in. Leave it empty and emails carry no link, and nobody can sign in with Microsoft."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error} said={s.said}>
      <Field label="Web address" hint="e.g. https://lms.example.com.au" source={all.public_url.source}
             error={s.errors.public_url} onReset={() => void s.reset("public_url")}>
        {(id) => <input id={id} className="field" type="url" value={String(s.draft.public_url)}
                        onChange={(e) => s.set("public_url")(e.target.value)} />}
      </Field>
    </Section>
  );
}

function Uploads({ all, onSaved }: Props) {
  const s = useSection(all, ["upload_files_per_day", "upload_mb_per_day"], onSaved);
  return (
    <Section title="Uploads" sub="How much one person can send of their own (tickets' photos and signatures) in any 24 hours, so nobody can fill the server's disk. Module files have their own limit: 200 files and 5 GB."
             onSubmit={s.save} busy={s.action.busy} error={s.action.error} said={s.said}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Files a person can send in a day" hint="1 to 100000" source={all.upload_files_per_day.source}
               error={s.errors.upload_files_per_day} onReset={() => void s.reset("upload_files_per_day")}>
          {(id) => <input id={id} className="field" type="number" min={1} max={100000} value={String(s.draft.upload_files_per_day)}
                          onChange={(e) => s.set("upload_files_per_day")(e.target.value)} />}
        </Field>
        <Field label="MB a person can send in a day" hint="1000 MB is a GB" source={all.upload_mb_per_day.source}
               error={s.errors.upload_mb_per_day} onReset={() => void s.reset("upload_mb_per_day")}>
          {(id) => <input id={id} className="field" type="number" min={1} max={1000000} value={String(s.draft.upload_mb_per_day)}
                          onChange={(e) => s.set("upload_mb_per_day")(e.target.value)} />}
        </Field>
      </div>
    </Section>
  );
}
