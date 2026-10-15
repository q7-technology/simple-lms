import { Fragment, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ApiKey, ApiKeyMade } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";
import { ShownOnce } from "../ui/ShownOnce";

const SCOPES = [{ scope: "competencies:read", label: "Read who is current (the competency API)" }];

/** Keys for other systems: made, shown once, revoked. */
export function ApiKeys() {
  const keys = useLoad(() => api.get<ApiKey[]>("/v1/api-keys"), []);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState(["competencies:read"]);
  const [made, setMade] = useState<ApiKeyMade | null>(null);
  const [asking, setAsking] = useState<ApiKey | null>(null);
  const action = useAction();

  async function make(e: FormEvent) {
    e.preventDefault();
    let out: ApiKeyMade | null = null;
    if (await action.run(async () => { out = await api.post<ApiKeyMade>("/v1/api-keys", { name, scopes }); })) {
      setMade(out);
      setName("");
      keys.reload();
    }
  }

  async function revoke(k: ApiKey) {
    setAsking(null);
    if (await action.run(() => api.post(`/v1/api-keys/${k.id}/revoke`))) keys.reload();
  }

  return (
    <section className="card flex flex-col gap-3" aria-label="API keys" style={{ maxWidth: 720 }}>
      <div>
        <h2 className="m-0 text-lg font-extrabold">API keys</h2>
        <div className="small">Other systems read who is current with a key: <code>GET /v1/people/&#123;code&#125;/competencies</code>, and nothing else.</div>
      </div>
      <Problem error={action.error ?? keys.error} />
      {keys.data?.length === 0 && <div className="card small">None yet. Make one for each system that reads who is current, such as Simple TMS.</div>}
      {keys.data && keys.data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>For</th><th>Key</th><th>May</th><th>Last used</th><th /></tr></thead>
          <tbody>
            {keys.data.map((k) => (
              <Fragment key={k.id}>
              <tr>
                <td><b>{k.name}</b><span className="small block">by {k.created_by.name} · {formatDate(k.created_at.slice(0, 10))}</span></td>
                <td className="font-mono small">{k.prefix}…</td>
                <td className="small">{k.scopes.map((x) => SCOPES.find((s) => s.scope === x)?.label ?? x).join(", ")}</td>
                <td className="small">{k.last_used_at ? formatDate(k.last_used_at.slice(0, 10)) : "Never"}</td>
                <td>{k.revoked_at
                  ? <span className="pill t-grey">Revoked</span>
                  : <button type="button" className="btn danger" disabled={action.busy} onClick={() => setAsking(k)}
                            aria-expanded={asking?.id === k.id}>Revoke</button>}</td>
              </tr>
              {asking?.id === k.id && (
                <tr>
                  <td colSpan={5}>
                    <div className="flex flex-wrap items-center gap-3" role="alertdialog" aria-label={`Revoke ${k.name}'s key`}>
                      <span className="text-sm"><b>Revoke {k.name}'s key? Anything using it stops working, for good.</b></span>
                      <button type="button" className="btn danger" onClick={() => void revoke(k)}>Revoke it</button>
                      <button type="button" className="btn" autoFocus onClick={() => setAsking(null)}>Keep it</button>
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      {made && <ShownOnce label={`${made.name}'s key`} value={made.key} onDone={() => setMade(null)}
                         why={`Put it in ${made.name}'s settings: it sends it as its bearer token.`} />}
      <form className="card flex flex-col gap-3" aria-label="Make an API key" onSubmit={make}>
        <div className="eyebrow">Make an API key</div>
        <label className="label">Who it is for<input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Simple TMS" required /></label>
        <fieldset className="flex flex-col gap-1">
          <legend className="label mb-1">It may</legend>
          {SCOPES.map((s) => (
            <label key={s.scope} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={scopes.includes(s.scope)}
                     onChange={(e) => setScopes(e.target.checked ? [...scopes, s.scope] : scopes.filter((x) => x !== s.scope))} />
              {s.label}
            </label>
          ))}
        </fieldset>
        <div><button type="submit" className="btn primary" disabled={action.busy || scopes.length === 0}>Make key</button></div>
      </form>
    </section>
  );
}
