import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Page, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

/** Roles, and the competencies each requires. */
export function Roles() {
  const { can } = useAuth();
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const [open, setOpen] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const action = useAction();
  const role = roles.data?.items.find((r) => r.key === open);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (await action.run(() => api.post("/v1/roles", { key, name }))) {
      setOpen(key.trim().toLowerCase());
      setKey("");
      setName("");
      roles.reload();
    }
  }

  return (
    <main className="page">
      <h1>Roles</h1>
      {can("roles:write") && (
        <form className="flex flex-wrap items-end gap-3" onSubmit={add}>
          <label className="label">Key<input className="field" value={key} onChange={(e) => setKey(e.target.value)} placeholder="forklift-operator" required /></label>
          <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Forklift operator" required /></label>
          <button type="submit" className="btn primary" disabled={action.busy}>Add role</button>
        </form>
      )}
      <Problem error={action.error ?? roles.error} />
      <table className="tbl">
        <thead><tr><th>Role</th><th>Requires</th><th>People</th></tr></thead>
        <tbody>
          {roles.data?.items.map((r) => (
            <tr key={r.key} className="click" onClick={() => setOpen(r.key)}>
              <td><b>{r.name}</b><div className="small">{r.key}</div></td>
              <td className="small">{r.competencies.map((c) => c.name).join(", ") || "Nothing yet"}</td>
              <td>{r.people}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {role && <RoleDrawer key={role.key} role={role} onClose={() => setOpen(null)} onChanged={roles.reload} />}
    </main>
  );
}

function RoleDrawer({ role, onClose, onChanged }: { role: Role; onClose: () => void; onChanged: () => void }) {
  const { can } = useAuth();
  const competencies = useLoad(() => api.get<Page<Competency>>("/v1/competencies", { active: true }), []);
  const [name, setName] = useState(role.name);
  const [chosen, setChosen] = useState(role.competencies.map((c) => c.key));
  const action = useAction();
  const [saved, setSaved] = useState(false);
  const path = `/v1/roles/${encodeURIComponent(role.key)}`;

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaved(false);
    const ok = await action.run(async () => {
      if (name !== role.name) await api.patch(path, { name });
      await api.put(`${path}/requirements`, { competencies: chosen });
    });
    if (ok) { setSaved(true); onChanged(); }
  }

  return (
    <Drawer title={role.name} sub={`${role.key} · ${role.people} ${role.people === 1 ? "person" : "people"}`} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={save}>
        <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} disabled={!can("roles:write")} required /></label>
        <fieldset className="card flex flex-col gap-1">
          <legend className="eyebrow">Requires</legend>
          {competencies.data?.items.map((c) => (
            <label key={c.key} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={chosen.includes(c.key)} disabled={!can("roles:write")}
                     onChange={(e) => setChosen(e.target.checked ? [...chosen, c.key] : chosen.filter((k) => k !== c.key))} />
              {c.name} <span className="small">{c.kind}</span>
            </label>
          ))}
        </fieldset>
        <Problem error={action.error} />
        {saved && <div className="msg g" role="status">Saved. The matrix shows it now.</div>}
        {can("roles:write") && <button type="submit" className="btn primary" disabled={action.busy}>Save</button>}
      </form>
    </Drawer>
  );
}
