import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Kind, Page } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";

const KINDS: { kind: Kind; label: string }[] = [
  { kind: "module", label: "Online module" },
  { kind: "practical", label: "Practical sign-off" },
  { kind: "ticket", label: "Ticket or licence" },
  { kind: "policy", label: "Signed policy" },
];
const kindLabel = (k: Kind) => KINDS.find((x) => x.kind === k)?.label ?? k;
const months = (n: number | null) => (n ? `Every ${n} months` : "None");

/** Competencies: in step 1 just what each is called, its kind and its refresher. */
export function Competencies() {
  const { can } = useAuth();
  const list = useLoad(() => api.get<Page<Competency>>("/v1/competencies"), []);
  const [open, setOpen] = useState<string | null>(null);
  const [f, setF] = useState({ key: "", name: "", kind: "module" as Kind, refresher: "" });
  const action = useAction();
  const competency = list.data?.items.find((c) => c.key === open);

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await action.run(() => api.post("/v1/competencies", {
      key: f.key, name: f.name, kind: f.kind, refresher_months: f.refresher ? Number(f.refresher) : null,
    }));
    if (ok) { setF({ key: "", name: "", kind: "module", refresher: "" }); list.reload(); }
  }

  return (
    <main className="page">
      <h1>Competencies</h1>
      {can("competencies:write") && (
        <form className="flex flex-wrap items-end gap-3" onSubmit={add}>
          <label className="label">Key<input className="field" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} placeholder="site-induction" required /></label>
          <label className="label">Name<input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Site induction" required /></label>
          <label className="label">Kind
            <select className="field" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as Kind })}>
              {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
          </label>
          <label className="label">Refresher (months)
            <input className="field" style={{ width: 120 }} type="number" min={1} max={240} value={f.refresher}
                   onChange={(e) => setF({ ...f, refresher: e.target.value })} />
          </label>
          <button type="submit" className="btn primary" disabled={action.busy}>Add competency</button>
        </form>
      )}
      <Problem error={action.error ?? list.error} />
      <table className="tbl">
        <thead><tr><th>Competency</th><th>Kind</th><th>Refresher</th><th></th></tr></thead>
        <tbody>
          {list.data?.items.map((c) => (
            <tr key={c.key} className="click" onClick={() => setOpen(c.key)}>
              <td><b>{c.name}</b><div className="small">{c.key}</div></td>
              <td>{kindLabel(c.kind)}</td>
              <td>{months(c.refresher_months)}</td>
              <td>{!c.active && <span className="pill t-grey">Deactivated</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {competency && can("competencies:write") && (
        <CompetencyDrawer key={competency.key} competency={competency} onClose={() => setOpen(null)} onChanged={list.reload} />
      )}
    </main>
  );
}

function CompetencyDrawer({ competency, onClose, onChanged }: {
  competency: Competency; onClose: () => void; onChanged: () => void;
}) {
  const [name, setName] = useState(competency.name);
  const [refresher, setRefresher] = useState(competency.refresher_months?.toString() ?? "");
  const action = useAction();
  const path = `/v1/competencies/${encodeURIComponent(competency.key)}`;
  const done = async (fn: () => Promise<unknown>) => { if (await action.run(fn)) onChanged(); };

  return (
    <Drawer title={competency.name} sub={`${competency.key} · ${kindLabel(competency.kind)}`} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={(e) => {
        e.preventDefault();
        void done(() => api.patch(path, { name, refresher_months: refresher ? Number(refresher) : null }));
      }}>
        <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="label">Refresher (months; empty for none)
          <input className="field" type="number" min={1} max={240} value={refresher} onChange={(e) => setRefresher(e.target.value)} />
        </label>
        <div className="small">A new refresher changes everyone's status at once: status is worked out, never stored.</div>
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy}>Save</button>
      </form>
      {competency.active
        ? <button type="button" className="btn danger" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/deactivate`))}>Deactivate: no longer asked of anyone</button>
        : <button type="button" className="btn" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/reactivate`))}>Reactivate</button>}
    </Drawer>
  );
}
