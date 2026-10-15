import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, Kind, Page, PolicyVersion } from "../api/types";
import { formatDate } from "../lib/status";
import { useAuth } from "../auth/AuthContext";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";
import { ModuleEditor } from "./ModuleEditor";

const KINDS: { kind: Kind; label: string }[] = [
  { kind: "module", label: "Online module" },
  { kind: "practical", label: "Practical sign-off" },
  { kind: "ticket", label: "Ticket or licence" },
  { kind: "policy", label: "Signed policy" },
];
const kindLabel = (k: Kind) => KINDS.find((x) => x.kind === k)?.label ?? k;
const months = (n: number | null) => (n ? `Every ${n} months` : "None");

/** Competencies: what each is called, its kind and its refresher; a
 * policy's versions, a ticket's card expiry, and a module's pages and quiz. */
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
              <td><button type="button" className="rowbtn" onClick={() => setOpen(c.key)}>
                <b>{c.name}</b><span className="small block">{c.key}</span></button></td>
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
  const [cardExpires, setCardExpires] = useState(competency.card_expires ?? true);
  const action = useAction();
  const path = `/v1/competencies/${encodeURIComponent(competency.key)}`;
  const done = async (fn: () => Promise<unknown>) => { if (await action.run(fn)) onChanged(); };
  const ticket = competency.kind === "ticket";

  return (
    <Drawer title={competency.name} sub={`${competency.key} · ${kindLabel(competency.kind)}`} onClose={onClose}>
      <form className="flex flex-col gap-3" onSubmit={(e) => {
        e.preventDefault();
        void done(() => api.patch(path, {
          name, refresher_months: refresher ? Number(refresher) : null, ...(ticket ? { card_expires: cardExpires } : {}),
        }));
      }}>
        <label className="label">Name<input className="field" value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label className="label">Refresher (months; empty for none)
          <input className="field" type="number" min={1} max={240} value={refresher} onChange={(e) => setRefresher(e.target.value)} />
        </label>
        {ticket && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cardExpires} onChange={(e) => setCardExpires(e.target.checked)} />
            The card has an expiry date (people type it in, and it runs out then)
          </label>
        )}
        <div className="small">A new refresher changes everyone's status at once: status is worked out, never stored.</div>
        <Problem error={action.error} />
        <button type="submit" className="btn primary" disabled={action.busy}>Save</button>
      </form>
      {competency.kind === "policy" && <PolicyVersions policy={competency} />}
      {competency.kind === "module" && <ModuleEditor module={competency} />}
      {competency.active
        ? <button type="button" className="btn danger" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/deactivate`))}>Deactivate: no longer asked of anyone</button>
        : <button type="button" className="btn" disabled={action.busy}
                  onClick={() => void done(() => api.post(`${path}/reactivate`))}>Reactivate</button>}
    </Drawer>
  );
}

/** A policy's versions, newest first, and the next one. Each person signs the
 * newest; a new version asks everyone to sign again. */
function PolicyVersions({ policy }: { policy: Competency }) {
  const path = `/v1/policies/${encodeURIComponent(policy.key)}/versions`;
  const versions = useLoad(() => api.get<PolicyVersion[]>(path), [path]);
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  // it can't be undone and asks everyone to sign again: past version 1, ask once
  const [confirming, setConfirming] = useState(false);
  const action = useAction();
  const next = (versions.data?.[0]?.version ?? 0) + 1;

  async function publish(e: FormEvent) {
    e.preventDefault();
    if (next > 1 && !confirming) { setConfirming(true); return; }
    setConfirming(false);
    if (await action.run(() => api.post(path, { body, note: note.trim() || null }))) {
      setBody("");
      setNote("");
      versions.reload();
    }
  }

  return (
    <section className="flex flex-col gap-3" aria-label="Versions">
      <div className="eyebrow">Versions</div>
      <Problem error={versions.error} />
      {versions.data?.length === 0 && <div className="small">No version yet: nobody can sign it until there is one.</div>}
      {versions.data?.map((v, i) => (
        <details key={v.id} className="card" open={i === 0}>
          <summary className="text-sm"><b>Version {v.version}</b>{i === 0 && " · the one to sign"} · {formatDate(v.created_at.slice(0, 10))} by {v.published_by.name}</summary>
          {v.note && <div className="small mt-2">What changed: {v.note}</div>}
          <div className="text-sm mt-2" style={{ whiteSpace: "pre-wrap" }}>{v.body}</div>
        </details>
      ))}
      {!policy.active && <div className="small">Reactivate it to publish a new version.</div>}
      {policy.active && <form className="card flex flex-col gap-3" onSubmit={publish}>
        <div className="eyebrow">Publish version {next}</div>
        <label className="label">The policy's text
          <textarea className="field" style={{ height: 160 }} value={body} maxLength={50000} onChange={(e) => setBody(e.target.value)} required />
        </label>
        <label className="label">What changed (optional)
          <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </label>
        {next > 1 && <div className="small">Everyone asked for this policy will need to sign version {next}.</div>}
        <Problem error={action.error} />
        {confirming ? (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm"><b>Publish version {next}? Everyone asked for this policy signs again.</b></span>
            <button type="submit" className="btn primary" disabled={action.busy || !body.trim()}>Publish</button>
            <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        ) : (
          <button type="submit" className="btn primary" disabled={action.busy || !body.trim()}>Publish version {next}</button>
        )}
      </form>}
    </section>
  );
}
