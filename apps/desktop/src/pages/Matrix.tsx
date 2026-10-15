import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CompetencyRef, Matrix as MatrixData, MatrixRow, Page, Permission, Person, Role, Status } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { LOOK, STATUSES, describe } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { HistoryDrawer } from "./HistoryDrawer";

const SUPERVISES: Permission[] = ["supervisor", "manager", "admin"];

/** People down the side, what they are asked for across the top. */
export function Matrix() {
  const { me } = useAuth();
  // the role is in the address, so a desk in the classroom opens the matrix
  // at its role, and a refresh or a link keeps it
  const [params, setParams] = useSearchParams();
  const role = params.get("role") ?? "";
  const setRole = (key: string) => {
    const next = new URLSearchParams(params);
    if (key) next.set("role", key);
    else next.delete("role");
    setParams(next, { replace: true });
  };
  const [supervisor, setSupervisor] = useState("");
  const [status, setStatus] = useState<"" | Status>("");
  // the row and competency as they were when opened: a filter can hide them after a change
  const [open, setOpen] = useState<{ row: MatrixRow; competency: CompetencyRef } | null>(null);
  const filters = { role, supervisor, status };
  const matrix = useLoad(() => api.get<MatrixData>("/v1/matrix", filters), [role, supervisor, status]);
  const roles = useLoad(() => api.get<Page<Role>>("/v1/roles"), []);
  const seesEveryone = me?.permission === "manager" || me?.permission === "admin";
  // everyone who can supervise, not just those in the filtered matrix, so choosing one keeps the rest
  const people = useLoad(() => seesEveryone ? api.get<Page<Person>>("/v1/people", { active: true }) : Promise.resolve(null),
                         [seesEveryone]);
  const exported = useAction();

  const supervisors = useMemo(() => (people.data?.items ?? [])
    .filter((p) => SUPERVISES.includes(p.permission))
    .sort((a, b) => a.name.localeCompare(b.name)), [people.data]);

  const m = matrix.data;
  const row = open && (m?.people.find((p) => p.code === open.row.code) ?? open.row);
  const competency = open && (m?.competencies.find((c) => c.key === open.competency.key) ?? open.competency);

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
                onClick={() => void exported.run(() => api.download("/v1/matrix.csv", filters, `matrix-${m?.today}.csv`))}>
          Export CSV
        </button>
      </div>
      <div className="flex flex-wrap gap-2" aria-label="Key">
        {(["current", "expiring", "lapsed", "missing", "waived"] as Status[]).map((s) => (
          <span key={s} className={`pill t-${LOOK[s].tone}`}>{LOOK[s].label}</span>
        ))}
      </div>
      <Problem error={matrix.error} />
      <Problem error={exported.error} />
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
                  <th scope="row" className="rowh"><b>{p.name}</b><div className="small">{p.code}</div></th>
                  <td className="small">{p.roles.map((r) => r.name).join(", ") || "No role yet"}</td>
                  {m.competencies.map((c) => {
                    const cell = p.cells[c.key];
                    const look = LOOK[cell.status];
                    const says = `${p.name}, ${c.name}: ${describe(cell)}`;
                    return (
                      <td key={c.key}>
                        <button type="button" className={`cell t-${look.tone}`} title={says} aria-label={says}
                                onClick={() => setOpen({ row: p, competency: c })}>{look.short}</button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && row && competency && m && (
        <HistoryDrawer person={row} competency={competency} cell={row.cells[competency.key] ?? open.row.cells[open.competency.key]} today={m.today}
                       onClose={() => setOpen(null)} onChanged={matrix.reload} />
      )}
    </main>
  );
}
