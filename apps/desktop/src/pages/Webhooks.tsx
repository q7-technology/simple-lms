import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { Delivery, EventType, Webhook, WebhookMade } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Drawer, Problem } from "../ui/Drawer";
import { ShownOnce } from "../ui/ShownOnce";

const EVENTS: { type: EventType; label: string }[] = [
  { type: "competency.granted", label: "Granted" },
  { type: "competency.revoked", label: "Revoked" },
  { type: "competency.expiring", label: "Expiring" },
  { type: "competency.lapsed", label: "Lapsed" },
  { type: "person.updated", label: "Person updated" },
];

const DELIVERY: Record<Delivery["status"], { label: string; tone: string }> = {
  pending: { label: "Waiting", tone: "t-amber" },
  done: { label: "Sent", tone: "t-green" },
  failed: { label: "Failed", tone: "t-red" },
};

const FIELDS: Record<string, string> = { name: "Name", url: "Address", events: "Events", active: "On" };

/** A change, with what the API says is wrong in the words on the screen. */
async function plainly<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError && e.errors.length > 0) {
      throw new Error(e.errors.map((x) => `${FIELDS[x.field.split(".")[0]] ?? x.field}: ${x.message}`).join("; "));
    }
    throw e;
  }
}

function wants(events: string[]): string {
  if (events.includes("*")) return "Everything";
  return EVENTS.filter((e) => events.includes(e.type)).map((e) => e.label).join(", ");
}

/** "2026-10-12T01:30:00Z" → "12 Oct 2026 12:30", in this browser's time. */
function when(iso: string): string {
  const d = new Date(iso);
  const day = formatDate(`${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`);
  return `${day} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Which events: each of the five, or everything (and whatever comes later). */
function EventPicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const all = value.includes("*");
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="label mb-1">Events</legend>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={all} onChange={(e) => onChange(e.target.checked ? ["*"] : [])} />
        Everything, and whatever is added later
      </label>
      {EVENTS.map((e) => (
        <label key={e.type} className="flex items-center gap-2 text-sm" title={e.type}>
          <input type="checkbox" disabled={all} checked={all || value.includes(e.type)}
                 onChange={(x) => onChange(x.target.checked ? [...value, e.type] : value.filter((t) => t !== e.type))} />
          {e.label}
        </label>
      ))}
    </fieldset>
  );
}

/** Where the events go. */
export function Webhooks() {
  const hooks = useLoad(() => api.get<Webhook[]>("/v1/webhooks"), []);
  const [open, setOpen] = useState<number | null>(null);
  const [made, setMade] = useState<WebhookMade | null>(null);
  const [f, setF] = useState({ name: "", url: "", events: [] as string[] });
  const action = useAction();
  const hook = hooks.data?.find((w) => w.id === open);

  async function add(e: FormEvent) {
    e.preventDefault();
    let out: WebhookMade | null = null;
    const ok = await action.run(async () => { out = await plainly(() => api.post<WebhookMade>("/v1/webhooks", f)); });
    if (ok) {
      setMade(out);
      setF({ name: "", url: "", events: [] });
      hooks.reload();
    }
  }

  return (
    <section className="card flex flex-col gap-3" aria-label="Webhooks" style={{ maxWidth: 720 }}>
      <div>
        <h2 className="m-0 text-lg font-extrabold">Webhooks</h2>
        <div className="small">Other systems hear what happens here: a competency granted, revoked, expiring or lapsed, a person changed. docs/api.md says what each is sent and how to check its signature.</div>
      </div>
      <Problem error={hooks.error} />
      {hooks.data?.length === 0 && <div className="card small">None yet. Add one for each system that should hear when someone is granted a competency, loses one, or changes.</div>}
      {hooks.data && hooks.data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Address</th><th>Events</th><th>Deliveries</th></tr></thead>
          <tbody>
            {hooks.data.map((w) => (
              <tr key={w.id} className="click" onClick={() => setOpen(w.id)}>
                <td><button type="button" className="rowbtn" onClick={() => setOpen(w.id)}><b>{w.name}</b></button>
                  {!w.active && <span className="pill t-grey ml-2">Off</span>}</td>
                <td className="small break-all">{w.url}</td>
                <td className="small">{wants(w.events)}</td>
                <td>
                  {w.failed > 0 && <span className="pill t-red">{w.failed} failed</span>}
                  {w.waiting > 0 && <span className="pill t-amber ml-1">{w.waiting} waiting</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {made && <ShownOnce label={`${made.name}'s secret`} value={made.secret} onDone={() => setMade(null)}
                         why="Give it to whoever looks after the receiver: it checks each event's X-LMS-Signature with it." />}
      <form className="card flex flex-col gap-3" aria-label="Add a webhook" onSubmit={add}>
        <div className="eyebrow">Add a webhook</div>
        <div className="grid grid-cols-2 gap-3">
          <label className="label">Name<input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Simple TMS" required /></label>
          <label className="label">Address<input className="field" type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://…" required /></label>
        </div>
        <EventPicker value={f.events} onChange={(events) => setF({ ...f, events })} />
        <Problem error={action.error} />
        <div><button type="submit" className="btn primary" disabled={action.busy || f.events.length === 0}>Add webhook</button></div>
      </form>
      {hook && <WebhookDrawer key={hook.id} hook={hook} onClose={() => setOpen(null)} onChanged={hooks.reload} />}
    </section>
  );
}

function WebhookDrawer({ hook, onClose, onChanged }: { hook: Webhook; onClose: () => void; onChanged: () => void }) {
  const path = `/v1/webhooks/${hook.id}`;
  const deliveries = useLoad(() => api.get<Delivery[]>(`${path}/deliveries`), [path]);
  const [f, setF] = useState({ name: hook.name, url: hook.url, events: hook.events, active: hook.active });
  const [said, setSaid] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  // turning it off gives up what is waiting for it: asked first
  const [askingOff, setAskingOff] = useState(false);
  const action = useAction();

  async function change(what: string, fn: () => Promise<unknown>) {
    setSaid(null);
    if (await action.run(fn)) {
      setSaid(what);
      deliveries.reload();
      onChanged();
    }
  }

  function save(e?: FormEvent) {
    e?.preventDefault();
    if (hook.active && !f.active && !askingOff) { setSaid(null); setAskingOff(true); return; }
    setAskingOff(false);
    void change("Saved.", () => plainly(() => api.patch(path, f)));
  }

  return (
    <Drawer title={hook.name} sub={hook.url} onClose={onClose}>
      <Problem error={action.error} />
      {said && <div className="msg g" role="status">{said}</div>}
      <form className="card flex flex-col gap-3" onSubmit={save}>
        <label className="label">Name<input className="field" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></label>
        <label className="label">Address<input className="field" type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} required /></label>
        <EventPicker value={f.events} onChange={(events) => setF({ ...f, events })} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
          On: events are sent to it
        </label>
        {askingOff
          ? (
            <div className="flex flex-wrap items-center gap-3" role="alertdialog" aria-label="Turn it off">
              <span className="text-sm"><b>Turn {hook.name} off? What is waiting for it is given up on, and nothing more is sent until it is on again.</b></span>
              <button type="button" className="btn danger" onClick={() => save()}>Turn it off</button>
              <button type="button" className="btn" autoFocus onClick={() => setAskingOff(false)}>Keep it on</button>
            </div>
          )
          : <div><button type="submit" className="btn primary" disabled={action.busy || f.events.length === 0}>Save</button></div>}
      </form>
      <div className="card flex flex-col gap-2">
        <div className="eyebrow">Secret</div>
        <div className="small">A new one signs everything sent from now on, what is waiting too; the old one stops at once.</div>
        {secret
          ? <ShownOnce label={`${hook.name}'s secret`} value={secret} onDone={() => setSecret(null)}
                       why="Give it to whoever looks after the receiver." />
          : <div><button type="button" className="btn" disabled={action.busy}
                         onClick={() => void action.run(async () => {
                           setSecret((await api.post<{ secret: string }>(`${path}/secret`)).secret);
                         })}>New secret</button></div>}
      </div>
      <section className="flex flex-col gap-2" aria-label="Deliveries">
        <div className="eyebrow">Latest deliveries</div>
        <Problem error={deliveries.error} />
        {deliveries.data?.length === 0 && <div className="small">Nothing sent yet.</div>}
        <ul className="flex flex-col gap-2">
          {deliveries.data?.map((d) => (
            <li key={d.id} className="card flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <span className={`pill ${DELIVERY[d.status].tone}`}>{DELIVERY[d.status].label}</span>
                <span className="text-sm">{d.event_type}</span>
                <span className="small ml-auto">{when(d.created_at)}</span>
              </div>
              {d.last_error && <div className="small">After {d.attempts} {d.attempts === 1 ? "try" : "tries"}: {d.last_error}</div>}
              {d.status === "failed" && (
                <div><button type="button" className="btn" disabled={action.busy}
                             onClick={() => void change("Sending it again.", () => api.post(`${path}/deliveries/${d.id}/retry`))}>
                  Send again</button></div>
              )}
            </li>
          ))}
        </ul>
      </section>
    </Drawer>
  );
}
