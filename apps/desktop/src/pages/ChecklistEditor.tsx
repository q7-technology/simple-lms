import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Checklist, Competency } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem, useCloseGuard } from "../ui/Drawer";

/** The most items a checklist has, as the API has it. */
const MOST = 50;

/** An item as it is written; `uid` keeps it itself as it moves. */
interface Line { uid: number; text: string }
let uids = 0;
const lines = (texts: string[]): Line[] => texts.map((text) => ({ uid: ++uids, text }));

function move<T>(list: T[], from: number, to: number): T[] {
  const out = [...list];
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}

/** A practical's checklist: what a supervisor watches the learner do, and
 * ticks. The version supervisors tick now is shown as it is; the next is
 * written whole, starting as a copy, and publishing freezes it, so every
 * sign-off says what was ticked. Sign-offs so far still count. */
export function ChecklistEditor({ practical }: { practical: Competency }) {
  const path = `/v1/practicals/${encodeURIComponent(practical.key)}/versions`;
  const versions = useLoad(() => api.get<Checklist[]>(path), [path]);
  const newest = versions.data?.[0] ?? null;

  return (
    <section className="flex flex-col gap-3" aria-label="Checklist">
      <div className="eyebrow">Checklist</div>
      <Problem error={versions.error} />
      {versions.data?.length === 0 && <div className="small">No checklist yet: nobody can be signed off until there is one.</div>}
      {newest && (
        <div className="card flex flex-col gap-2 text-sm">
          <div><b>Version {newest.version}</b> is the one supervisors tick · published {formatDate(newest.created_at.slice(0, 10))} by {newest.published_by.name}</div>
          {newest.note && <div className="small">What changed: {newest.note}</div>}
          <ol className="list-decimal pl-5">{newest.items.map((i) => <li key={i.id}>{i.text}</li>)}</ol>
        </div>
      )}
      {versions.data && (practical.active
        ? <NextVersion key={newest?.id ?? 0} path={path} from={newest} onPublished={versions.reload} />
        : <div className="small">Reactivate it to publish a new checklist.</div>)}
    </section>
  );
}

function NextVersion({ path, from, onPublished }: { path: string; from: Checklist | null; onPublished: () => void }) {
  const start = from ? from.items.map((i) => i.text) : [""];
  const [items, setItems] = useState<Line[]>(() => lines(start));
  const [note, setNote] = useState("");
  // it can't be undone: ask once
  const [confirming, setConfirming] = useState(false);
  const action = useAction();
  const next = (from?.version ?? 0) + 1;
  const texts = items.map((i) => i.text.trim());
  const same = texts.join("\n") === start.join("\n");
  const ready = texts.length > 0 && texts.every(Boolean) && !same;
  useCloseGuard(same && !note.trim() ? null : `Version ${next} has changes that aren't published.`);

  const edit = (change: (ls: Line[]) => Line[]) => { setConfirming(false); setItems(change); };

  async function publish(e: FormEvent) {
    e.preventDefault();
    if (!confirming) { setConfirming(true); return; }
    setConfirming(false);
    if (await action.run(() => api.post(path, { items: texts, note: note.trim() || null }))) onPublished();
  }

  return (
    <form className="card flex flex-col gap-3" onSubmit={publish} aria-label={`Version ${next}`}>
      <div className="eyebrow">Version {next}</div>
      {from && <div className="small">Version {next} starts as a copy of version {from.version}. Supervisors tick version {from.version} until you publish it, and sign-offs so far still count.</div>}
      <ol className="flex flex-col gap-2">
        {items.map((item, i) => (
          <li key={item.uid} className="flex items-center gap-2">
            <input className="field" aria-label={`Item ${i + 1}`} value={item.text} maxLength={300}
                   placeholder="e.g. Checks the forks, chains and tyres"
                   onChange={(e) => { const text = e.target.value; edit((ls) => ls.map((l) => (l.uid === item.uid ? { ...l, text } : l))); }} />
            <button type="button" className="btn" disabled={i === 0} aria-label={`Move item ${i + 1} up`} onClick={() => edit((ls) => move(ls, i, i - 1))}>↑</button>
            <button type="button" className="btn" disabled={i === items.length - 1} aria-label={`Move item ${i + 1} down`} onClick={() => edit((ls) => move(ls, i, i + 1))}>↓</button>
            <button type="button" className="btn danger" aria-label={`Remove item ${i + 1}`} onClick={() => edit((ls) => ls.filter((l) => l.uid !== item.uid))}>Remove</button>
          </li>
        ))}
      </ol>
      <button type="button" className="btn" disabled={items.length >= MOST} onClick={() => edit((ls) => [...ls, ...lines([""])])}>Add an item</button>
      <label className="label">What changed (optional)
        <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </label>
      {same && <div className="small">Change an item to publish a new version.</div>}
      <Problem error={action.error} />
      {confirming ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm"><b>Publish version {next}? Its items are frozen once it is, and every sign-off from now on ticks them.</b></span>
          <button type="submit" className="btn primary" disabled={action.busy}>Publish</button>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button type="submit" className="btn primary" disabled={action.busy || !ready}>Publish version {next}</button>
      )}
    </form>
  );
}
