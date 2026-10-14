import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Cell, CompetencyRecord, CompetencyRef, PersonRef } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LOOK, describe, formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";
import { Picture } from "../ui/Picture";

/** One person's history for one competency, newest first: the first row is
 * the one that counts. A manager records a completion or revokes one here. */
export function HistoryDrawer({ person, competency, cell, today, onClose, onChanged }: {
  person: PersonRef; competency: CompetencyRef; cell: Cell; today: string;
  onClose: () => void; onChanged: () => void;
}) {
  const { me, can } = useAuth();
  const path = `/v1/people/${encodeURIComponent(person.code)}/records`;
  const history = useLoad(() => api.get<CompetencyRecord[]>(path, { competency: competency.key }),
                          [path, competency.key]);
  const [grantedOn, setGrantedOn] = useState(today);
  const [expiresOn, setExpiresOn] = useState("");
  const [note, setNote] = useState("");
  const [why, setWhy] = useState("");
  const action = useAction();
  const own = me?.code === person.code;
  const granted = history.data?.[0]?.kind === "granted";

  async function changed(fn: () => Promise<unknown>) {
    if (await action.run(fn)) {
      setNote("");
      setWhy("");
      setExpiresOn("");
      history.reload();
      onChanged();
    }
  }

  function record(e: FormEvent) {
    e.preventDefault();
    void changed(() => api.post(path, {
      competency: competency.key, granted_on: grantedOn, expires_on: expiresOn || null, note: note.trim() || null,
    }));
  }

  function revoke(e: FormEvent) {
    e.preventDefault();
    void changed(() => api.post(`${path}/revoke`, { competency: competency.key, note: why.trim() }));
  }

  return (
    <Drawer title={competency.name} sub={`${person.name} · ${person.code}`} onClose={onClose}>
      <div className="flex items-center gap-2">
        <span className={`pill t-${LOOK[cell.status].tone}`}>{LOOK[cell.status].label}</span>
        <span className="small">{describe(cell)}</span>
      </div>
      <Problem error={action.error ?? history.error} />
      {can("records:write") && own && (
        <div className="msg r">Nobody records their own competency: ask another manager.</div>
      )}
      {can("records:write") && !own && (
        <form className="card flex flex-col gap-3" onSubmit={record}>
          <div className="eyebrow">Record completion</div>
          <div className="grid grid-cols-2 gap-3">
            <label className="label">Completed on
              <input className="field" type="date" max={today} value={grantedOn}
                     onChange={(e) => setGrantedOn(e.target.value)} required />
            </label>
            <label className="label">Good until (optional)
              <input className="field" type="date" value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} />
            </label>
          </div>
          <div className="small">Leave “Good until” empty to use the competency's refresher, or for no expiry.</div>
          <label className="label">Note (optional)
            <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)}
                   placeholder="e.g. licence number, who ran the session" />
          </label>
          <button type="submit" className="btn primary" disabled={action.busy}>Record completion</button>
        </form>
      )}
      {can("records:write") && granted && (
        <form className="card flex flex-col gap-3" onSubmit={revoke}>
          <div className="eyebrow">Revoke</div>
          <label className="label">Why
            <input className="field" value={why} maxLength={500} onChange={(e) => setWhy(e.target.value)}
                   placeholder="e.g. ticked for the wrong person" required />
          </label>
          <button type="submit" className="btn danger" disabled={action.busy || !why.trim()}>Revoke</button>
        </form>
      )}
      <section className="flex flex-col gap-2" aria-label="History">
        <div className="eyebrow">History</div>
        {history.data?.length === 0 && <div className="small">Nothing recorded yet.</div>}
        {history.data?.map((r, i) => (
          <div key={r.id} className="card flex flex-col gap-1" style={{ opacity: i === 0 ? 1 : 0.75 }}>
            <div className="flex items-center gap-2">
              <span className={`pill ${r.kind === "granted" ? "t-green" : "t-red"}`}>
                {r.kind === "granted" ? "Completed" : "Revoked"}</span>
              {r.kind === "granted" && (
                <span className="text-sm">{formatDate(r.granted_on)}
                  {r.expires_on && <> · good until {formatDate(r.expires_on)}</>}</span>
              )}
              {i === 0 && <span className="small ml-auto">Counts now</span>}
            </div>
            {r.policy_version && (
              <div className="text-sm">{r.signed_name
                ? <>Signed version {r.policy_version} as “{r.signed_name}”</>
                : <>For version {r.policy_version}</>}</div>
            )}
            {r.signature && <Picture upload={r.signature} label={`${person.name}'s signature`} width={200} />}
            {r.note && <div className="text-sm">{r.note}</div>}
            <div className="small">by {r.recorded_by.name} · {formatDate(r.created_at.slice(0, 10))}</div>
          </div>
        ))}
      </section>
    </Drawer>
  );
}
