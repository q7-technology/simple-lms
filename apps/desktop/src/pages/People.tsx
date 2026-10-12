import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Override, Page, Permission, Person, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

const PERMISSIONS: Permission[] = ["learner", "supervisor", "manager", "admin"];
const SUPERVISES: Permission[] = ["supervisor", "manager", "admin"];

/** People: added, changed, deactivated. Never deleted. */
export function People() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [open, setOpen] = useState<string | "new" | null>(null);
  const people = useLoad(() => api.get<Page<Person>>("/v1/people", { q, active: showInactive ? undefined : true }),
                         [q, showInactive]);
  const everyone = useLoad(() => api.get<Page<Person>>("/v1/people", { active: true }), []);
  const supervisors = (everyone.data?.items ?? []).filter((p) => SUPERVISES.includes(p.permission));
  const changed = () => { people.reload(); everyone.reload(); };

  return (
    <main className="page">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto">People</h1>
        <input className="field" style={{ width: 260 }} placeholder="Search code, name or email" aria-label="Search"
               value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="small flex items-center gap-2">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show deactivated</label>
        {can("people:write") && <button type="button" className="btn primary" onClick={() => setOpen("new")}>Add person</button>}
      </div>
      <Problem error={people.error} />
      <table className="tbl">
        <thead><tr><th>Name</th><th>Code</th><th>Permission</th><th>Roles</th><th>Supervisor</th><th>Sign-in</th></tr></thead>
        <tbody>
          {people.data?.items.map((p) => (
            <tr key={p.code} className="click" onClick={() => setOpen(p.code)}>
              <td><b>{p.name}</b>{!p.active && <span className="pill t-grey ml-2">Deactivated</span>}</td>
              <td>{p.code}</td>
              <td>{p.permission}</td>
              <td className="small">{p.roles.map((r) => r.name).join(", ")}</td>
              <td className="small">{p.supervisor?.name ?? ""}</td>
              <td className="small">
                {[p.has_pin && "PIN", p.has_password && "password"].filter(Boolean).join(" and ") || "none"}
                {p.pin_locked && <span className="pill t-red ml-2">PIN locked</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open === "new" && (
        <NewPerson supervisors={supervisors} onClose={() => setOpen(null)}
                   onDone={(code) => { changed(); setOpen(code); }} />
      )}
      {open && open !== "new" && (
        <PersonDrawer code={open} supervisors={supervisors} onClose={() => setOpen(null)} onChanged={changed} />
      )}
    </main>
  );
}

function usePermissionsICanGive(): Permission[] {
  const { me } = useAuth();
  return me?.permission === "admin" ? PERMISSIONS : ["learner", "supervisor"];
}

function SupervisorSelect({ value, onChange, supervisors, not }: {
  value: string; onChange: (v: string) => void; supervisors: Person[]; not?: string;
}) {
  return (
    <label className="label">Supervisor
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Nobody</option>
        {supervisors.filter((s) => s.code !== not).map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
      </select>
    </label>
  );
}

function RoleBoxes({ roles, chosen, onChange }: { roles: Role[]; chosen: string[]; onChange: (keys: string[]) => void }) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="label mb-1">Roles</legend>
      {roles.length === 0 && <div className="small">No roles yet: add them under Roles.</div>}
      {roles.map((r) => (
        <label key={r.key} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={chosen.includes(r.key)}
                 onChange={(e) => onChange(e.target.checked ? [...chosen, r.key] : chosen.filter((k) => k !== r.key))} />
          {r.name}
        </label>
      ))}
    </fieldset>
  );
}

function NewPerson({ supervisors, onClose, onDone }: {
  supervisors: Person[]; onClose: () => void; onDone: (code: string) => void;
}) {
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const permissions = usePermissionsICanGive();
  const [f, setF] = useState({ code: "", name: "", email: "", permission: "learner" as Permission,
                               supervisor: "", pin: "", password: "" });
  const [chosen, setChosen] = useState<string[]>([]);
  const action = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    let code = "";
    const ok = await action.run(async () => {
      const out = await api.post<Person>("/v1/people", {
        code: f.code, name: f.name, email: f.email || null, permission: f.permission,
        supervisor: f.supervisor || null, roles: chosen, pin: f.pin || null, password: f.password || null,
      });
      code = out.code;
    });
    if (ok) onDone(code);
  }

  return (
    <Drawer title="Add person" onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">Code<input className="field" value={f.code} onChange={set("code")} placeholder="e.g. LL042" required /></label>
          <label className="label">Name<input className="field" value={f.name} onChange={set("name")} required /></label>
        </div>
        <label className="label">Email (optional)<input className="field" type="email" value={f.email} onChange={set("email")} /></label>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">Permission
            <select className="field" value={f.permission} onChange={set("permission")}>
              {permissions.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <SupervisorSelect value={f.supervisor} onChange={(v) => setF({ ...f, supervisor: v })} supervisors={supervisors} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">PIN (4 to 8 digits)
            <input className="field" inputMode="numeric" pattern="[0-9]{4,8}" value={f.pin} onChange={set("pin")} />
          </label>
          <label className="label">Password (12 or more)
            <input className="field" type="password" minLength={12} autoComplete="new-password" value={f.password} onChange={set("password")} />
          </label>
        </div>
        <RoleBoxes roles={roles.data?.items ?? []} chosen={chosen} onChange={setChosen} />
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy}>Add person</button>
      </form>
    </Drawer>
  );
}

function PersonDrawer({ code, supervisors, onClose, onChanged }: {
  code: string; supervisors: Person[]; onClose: () => void; onChanged: () => void;
}) {
  const { me } = useAuth();
  const path = `/v1/people/${encodeURIComponent(code)}`;
  const person = useLoad(() => api.get<Person>(path), [path]);
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const competencies = useLoad(() => api.get<Page<Competency>>("/v1/competencies", { active: true }), []);
  const overrides = useLoad(() => api.get<Override[]>(`${path}/overrides`), [path]);
  const permissions = usePermissionsICanGive();
  const action = useAction();
  const [said, setSaid] = useState<string | null>(null);
  const p = person.data;
  if (!p) return <Drawer title={code} onClose={onClose}><Problem error={person.error} /></Drawer>;
  const mine = me?.permission === "admin" || !["manager", "admin"].includes(p.permission);

  async function change(what: string, fn: () => Promise<unknown>) {
    setSaid(null);
    if (await action.run(fn)) {
      setSaid(what);
      person.reload();
      overrides.reload();
      onChanged();
    }
  }

  return (
    <Drawer title={p.name} sub={`${p.code} · ${p.permission}${p.active ? "" : " · deactivated"}`} onClose={onClose}>
      <Problem error={action.error} />
      {said && <div className="msg g" role="status">{said}</div>}
      {!mine && <div className="msg r">Only an admin can change a manager or an admin.</div>}
      {mine && (
        <>
          <Details key={`d${p.code}${p.name}${p.email}${p.permission}${p.supervisor?.code}`} person={p}
                   permissions={permissions} supervisors={supervisors} busy={action.busy}
                   onSave={(body) => change("Saved.", () => api.patch(path, body))} />
          <RolesCard key={`r${p.roles.map((r) => r.key).join()}`} person={p} roles={roles.data?.items ?? []} busy={action.busy}
                 onSave={(keys) => change("Roles saved.", () => api.put(`${path}/roles`, { roles: keys }))} />
          <Overrides current={overrides.data ?? []} competencies={competencies.data?.items ?? []} busy={action.busy}
                     onAdd={(body) => change("Saved.", () => api.post(`${path}/overrides`, body))} />
          <Secret label={p.pin_locked ? "New PIN (unlocks it)" : "New PIN"} kind="pin" busy={action.busy}
                  onSave={(pin) => change("PIN set.", () => api.post(`${path}/pin`, { pin }))} />
          <Secret label="New password" kind="password" busy={action.busy}
                  onSave={(password) => change("Password set.", () => api.post(`${path}/password`, { password }))} />
          <div>
            {p.active
              ? <button type="button" className="btn danger" disabled={action.busy}
                        onClick={() => void change("Deactivated. Their records stay.", () => api.post(`${path}/deactivate`))}>Deactivate</button>
              : <button type="button" className="btn" disabled={action.busy}
                        onClick={() => void change("Reactivated.", () => api.post(`${path}/reactivate`))}>Reactivate</button>}
          </div>
        </>
      )}
    </Drawer>
  );
}

function Details({ person, permissions, supervisors, busy, onSave }: {
  person: Person; permissions: Permission[]; supervisors: Person[]; busy: boolean; onSave: (body: unknown) => void;
}) {
  const [name, setName] = useState(person.name);
  const [email, setEmail] = useState(person.email ?? "");
  const [permission, setPermission] = useState(person.permission);
  const [supervisor, setSupervisor] = useState(person.supervisor?.code ?? "");
  return (
    <form className="card flex flex-col gap-3" onSubmit={(e) => {
      e.preventDefault();
      onSave({ name, email: email || null, permission, supervisor: supervisor || null });
    }}>
      <div className="eyebrow">Details</div>
      <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} required /></label>
      <label className="label">Email<input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <div className="grid grid-cols-2 gap-3">
        <label className="label">Permission
          <select className="field" value={permission} onChange={(e) => setPermission(e.target.value as Permission)}>
            {permissions.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
        <SupervisorSelect value={supervisor} onChange={setSupervisor} supervisors={supervisors} not={person.code} />
      </div>
      <button type="submit" className="btn primary" disabled={busy}>Save details</button>
    </form>
  );
}

function RolesCard({ person, roles, busy, onSave }: { person: Person; roles: Role[]; busy: boolean; onSave: (keys: string[]) => void }) {
  const [chosen, setChosen] = useState(person.roles.map((r) => r.key));
  return (
    <div className="card flex flex-col gap-3">
      <RoleBoxes roles={roles} chosen={chosen} onChange={setChosen} />
      <button type="button" className="btn" disabled={busy} onClick={() => onSave(chosen)}>Save roles</button>
    </div>
  );
}

function Overrides({ current, competencies, busy, onAdd }: {
  current: Override[]; competencies: Competency[]; busy: boolean;
  onAdd: (body: { competency: string; kind: string; note: string }) => void;
}) {
  const [competency, setCompetency] = useState("");
  const [kind, setKind] = useState("extra");
  const [note, setNote] = useState("");
  return (
    <form className="card flex flex-col gap-3" onSubmit={(e) => {
      e.preventDefault();
      onAdd({ competency, kind, note: note.trim() });
      setNote("");
    }}>
      <div className="eyebrow">Extras and waivers</div>
      {current.length === 0 && <div className="small">None: their roles decide what they need.</div>}
      {current.map((o) => (
        <div key={o.id} className="text-sm">
          <span className={`pill ${o.kind === "extra" ? "t-amber" : "t-grey"}`}>{o.kind === "extra" ? "Extra" : "Waived"}</span>{" "}
          <b>{o.competency.name}</b> · {o.note} <span className="small">({o.recorded_by.name})</span>
        </div>
      ))}
      <div className="grid grid-cols-2 gap-3">
        <label className="label">Competency
          <select className="field" value={competency} onChange={(e) => setCompetency(e.target.value)} required>
            <option value="">Choose…</option>
            {competencies.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
          </select>
        </label>
        <label className="label">What
          <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="extra">Extra: needed by them too</option>
            <option value="waive">Waive: not needed by them</option>
            <option value="clear">Clear: back to their roles</option>
          </select>
        </label>
      </div>
      <label className="label">Note<input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} required /></label>
      <button type="submit" className="btn" disabled={busy || !note.trim() || !competency}>Save</button>
    </form>
  );
}

function Secret({ label, kind, busy, onSave }: { label: string; kind: "pin" | "password"; busy: boolean; onSave: (v: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <form className="card flex items-end gap-3" onSubmit={(e) => { e.preventDefault(); onSave(value); setValue(""); }}>
      <label className="label flex-1">{label}
        {kind === "pin"
          ? <input className="field" inputMode="numeric" pattern="[0-9]{4,8}" value={value} onChange={(e) => setValue(e.target.value)} required />
          : <input className="field" type="password" minLength={12} autoComplete="new-password" value={value} onChange={(e) => setValue(e.target.value)} required />}
      </label>
      <button type="submit" className="btn" disabled={busy}>Set {kind === "pin" ? "PIN" : "password"}</button>
    </form>
  );
}
