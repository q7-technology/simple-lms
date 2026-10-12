import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Matrix as MatrixData, Page, PersonRef, Role, Status } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LOOK, STATUSES, describe } from "../lib/status";
import { useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { HistoryDrawer } from "./HistoryDrawer";

/** People down the side, what they are asked for across the top. */
export function Matrix() {
  const { me } = useAuth();
  const [role, setRole] = useState("");
  const [supervisor, setSupervisor] = useState("");
  const [status, setStatus] = useState<"" | Status>("");
  const [open, setOpen] = useState<{ code: string; key: string } | null>(null);
  const filters = { role, supervisor, status };
  const matrix = useLoad(() => api.get<MatrixData>("/v1/matrix", filters), [role, supervisor, status]);
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const seesEveryone = me?.permission === "manager" || me?.permission === "admin";

  const supervisors = useMemo(() => {
    const all = new Map<string, PersonRef>();
    for (const p of matrix.data?.people ?? []) if (p.supervisor) all.set(p.supervisor.code, p.supervisor);
    return [...all.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [matrix.data]);

  const m = matrix.data;
  const row = open && m?.people.find((p) => p.code === open.code);
  const competency = open && m?.competencies.find((c) => c.key === open.key);

  return (
    <main className="page">
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto">Matrix</h1>
        <label className="label">Role
          <select className="field" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">All roles</option>
            {roles.data?.items.map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}
          </select>
        </label>
        {seesEveryone && (
          <label className="label">Supervisor
            <select className="field" value={supervisor} onChange={(e) => setSupervisor(e.target.value)}>
              <option value="">Anyone</option>
              {supervisors.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
          </label>
        )}
        <label className="label">Status
          <select className="field" value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            <option value="">Any</option>
            {STATUSES.filter((s) => s !== "not_required").map((s) => <option key={s} value={s}>{LOOK[s].label}</option>)}
          </select>
        </label>
        <button type="button" className="btn" disabled={!m}
                onClick={() => void api.download("/v1/matrix.csv", filters, `matrix-${m?.today}.csv`)}>
          Export CSV
        </button>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="Key">
        {(["current", "expiring", "lapsed", "missing", "waived"] as Status[]).map((s) => (
          <span key={s} className={`pill t-${LOOK[s].tone}`}>{LOOK[s].label}</span>
        ))}
      </div>
      <Problem error={matrix.error} />
      {m && m.people.length === 0 && <div className="card small">Nobody matches. Try fewer filters.</div>}
      {m && m.people.length > 0 && (
        <div className="overflow-x-auto">
          <table className="tbl matrix">
            <thead>
              <tr>
                <th>Person</th>
                <th>Roles</th>
                {m.competencies.map((c) => <th key={c.key} className="c" scope="col">{c.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {m.people.map((p) => (
                <tr key={p.code}>
                  <td><b>{p.name}</b><div className="small">{p.code}</div></td>
                  <td className="small">{p.roles.map((r) => r.name).join(", ") || "No role yet"}</td>
                  {m.competencies.map((c) => {
                    const cell = p.cells[c.key];
                    const look = LOOK[cell.status];
                    const says = `${p.name}, ${c.name}: ${describe(cell)}`;
                    return (
                      <td key={c.key}>
                        <button type="button" className={`cell t-${look.tone}`} title={says} aria-label={says}
                                onClick={() => setOpen({ code: p.code, key: c.key })}>{look.short}</button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {row && competency && m && (
        <HistoryDrawer person={row} competency={competency} cell={row.cells[competency.key]} today={m.today}
                       onClose={() => setOpen(null)} onChanged={matrix.reload} />
      )}
    </main>
  );
}
