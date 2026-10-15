import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Competency, ModulePage, ModuleVersion, PageKind, Question } from "../api/types";
import { formatDate } from "../lib/status";
import { useAction, useLoad } from "../lib/useLoad";
import { Problem } from "../ui/Drawer";

const KINDS: { kind: PageKind; label: string }[] = [
  { kind: "text", label: "Text" },
  { kind: "image", label: "Picture" },
  { kind: "pdf", label: "PDF" },
  { kind: "video", label: "Video" },
  { kind: "link", label: "Link" },
];
const kindLabel = (k: PageKind) => KINDS.find((x) => x.kind === k)?.label ?? k;

type FileKind = "image" | "pdf" | "video";
/** What each page's file may be, as the API has it: 200 MB for a video, 20 MB for the rest. */
const FILES: Record<FileKind, { accept: string; most: number }> = {
  image: { accept: "image/jpeg,image/png", most: 20_000_000 },
  pdf: { accept: "application/pdf", most: 20_000_000 },
  video: { accept: "video/mp4,video/webm", most: 200_000_000 },
};
const hasFile = (k: PageKind): k is FileKind => k in FILES;
const TYPES: Record<string, string> = {
  "image/jpeg": "JPEG", "image/png": "PNG", "application/pdf": "PDF", "video/mp4": "MP4", "video/webm": "WebM",
};
const megabytes = (bytes: number) => `${(bytes / 1_000_000).toFixed(1)} MB`;
const count = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** A page or question as it is being written; `uid` keeps it itself as it moves. */
interface PageFile { id: string; content_type: string; size_bytes: number; link: string | null }
interface Page { uid: number; kind: PageKind; title: string; body: string; url: string; file: PageFile | null }
interface Ask extends Question { uid: number }

let uids = 0;
const uid = () => ++uids;
const fromApi = (p: ModulePage): Page => ({ uid: uid(), kind: p.kind, title: p.title, body: p.body ?? "", url: p.url ?? "", file: p.file });

/** What the API takes for each kind of page, and nothing it doesn't. */
function toApi(p: Page) {
  const title = p.title.trim();
  if (p.kind === "text") return { kind: p.kind, title, body: p.body };
  const body = p.body.trim() || null;
  if (p.kind === "link") return { kind: p.kind, title, url: p.url.trim(), body };
  return { kind: p.kind, title, file: p.file?.id ?? null, body };
}

function move<T>(list: T[], from: number, to: number): T[] {
  const out = [...list];
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}

/** A module's pages and quiz. The version people take is shown as it is;
 * the next is written as a draft, saved as often as needed, then published,
 * which freezes it. */
export function ModuleEditor({ module }: { module: Competency }) {
  const path = `/v1/modules/${encodeURIComponent(module.key)}`;
  const versions = useLoad(() => api.get<ModuleVersion[]>(`${path}/versions`), [path]);
  const action = useAction();
  const draft = versions.data?.find((v) => !v.published_at);
  const live = versions.data?.find((v) => v.published_at);
  const next = (versions.data?.[0]?.version ?? 0) + 1;

  async function start() {
    if (await action.run(() => api.post(`${path}/draft`))) versions.reload();
  }

  return (
    <section className="flex flex-col gap-3" aria-label="Pages and quiz">
      <div className="eyebrow">Pages and quiz</div>
      <Problem error={versions.error ?? action.error} />
      {versions.data && !live && !draft && <div className="small">Nothing published yet: nobody can take it until there is a version.</div>}
      {live && (
        <div className="card text-sm">
          <b>Version {live.version}</b> is the one people take · published {formatDate(live.published_at!.slice(0, 10))}
          {live.published_by && <> by {live.published_by.name}</>}
          {` · ${count(live.pages.length, "page")} · ${count(live.questions.length, "question")} · pass mark ${live.pass_mark}%`}
        </div>
      )}
      {versions.data && !draft && (module.active ? (
        <>
          {live && <div className="small">Version {next} starts as a copy of version {live.version}. People keep taking version {live.version} until you publish it, and passes so far still count.</div>}
          <button type="button" className="btn primary" disabled={action.busy} onClick={() => void start()}>Start version {next}</button>
        </>
      ) : <div className="small">Reactivate it to write a new version.</div>)}
      {draft && <Draft key={draft.id} draft={draft} path={path} active={module.active} onPublished={versions.reload} />}
    </section>
  );
}

function Draft({ draft, path, active, onPublished }: {
  draft: ModuleVersion; path: string; active: boolean; onPublished: () => void;
}) {
  const [passMark, setPassMark] = useState(String(draft.pass_mark));
  const [pages, setPages] = useState<Page[]>(() => draft.pages.map(fromApi));
  const [questions, setQuestions] = useState<Ask[]>(() => draft.questions.map((q) => ({ ...q, uid: uid() })));
  const [adding, setAdding] = useState<PageKind>("text");
  const [saved, setSaved] = useState(false);
  // publishing can't be undone: ask once
  const [confirming, setConfirming] = useState(false);
  const action = useAction();
  const ready = pages.length > 0 && questions.length > 0;

  const changed = () => { setSaved(false); setConfirming(false); };
  const setPage = (i: number, change: Partial<Page>) => { changed(); setPages((ps) => ps.map((p, j) => (j === i ? { ...p, ...change } : p))); };
  const setQuestion = (i: number, change: Partial<Ask>) => { changed(); setQuestions((qs) => qs.map((q, j) => (j === i ? { ...q, ...change } : q))); };
  const body = () => ({
    pass_mark: Number(passMark),
    pages: pages.map(toApi),
    questions: questions.map((q) => ({ prompt: q.prompt.trim(), options: q.options.map((o) => o.trim()), correct: q.correct })),
  });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (await action.run(() => api.put(`${path}/draft`, body()))) setSaved(true);
  }

  async function publish() {
    if (!confirming) { setConfirming(true); return; }
    setConfirming(false);
    const done = await action.run(async () => {
      await api.put(`${path}/draft`, body());
      await api.post(`${path}/draft/publish`);
    });
    if (done) onPublished();
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={save}>
      <div className="small">Version {draft.version} is a draft: change it as often as you like, then publish it. Once it is published its pages and questions are frozen, so every attempt stays what was asked.</div>
      <label className="label">Pass mark (%)
        <input className="field" style={{ width: 120 }} type="number" min={1} max={100} value={passMark}
               onChange={(e) => { changed(); setPassMark(e.target.value); }} required />
      </label>

      <div className="eyebrow">Pages</div>
      {pages.length === 0 && <div className="small">No pages yet. People read them one at a time, then take the quiz.</div>}
      {pages.map((p, i) => (
        <PageCard key={p.uid} page={p} n={i + 1} count={pages.length} onChange={(c) => setPage(i, c)}
                  onMove={(by) => { changed(); setPages((ps) => move(ps, i, i + by)); }}
                  onRemove={() => { changed(); setPages((ps) => ps.filter((_, j) => j !== i)); }} />
      ))}
      <div className="flex items-end gap-2">
        <label className="label">New page
          <select className="field" value={adding} onChange={(e) => setAdding(e.target.value as PageKind)}>
            {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select>
        </label>
        <button type="button" className="btn" disabled={pages.length >= 100}
                onClick={() => { changed(); setPages((ps) => [...ps, { uid: uid(), kind: adding, title: "", body: "", url: "", file: null }]); }}>
          Add a page</button>
      </div>

      <div className="eyebrow">Quiz</div>
      {questions.length === 0 && <div className="small">No questions yet. Each has 2 to 6 answers, one of them right.</div>}
      {questions.map((q, i) => (
        <QuestionCard key={q.uid} question={q} n={i + 1} count={questions.length} onChange={(c) => setQuestion(i, c)}
                      onMove={(by) => { changed(); setQuestions((qs) => move(qs, i, i + by)); }}
                      onRemove={() => { changed(); setQuestions((qs) => qs.filter((_, j) => j !== i)); }} />
      ))}
      <button type="button" className="btn" disabled={questions.length >= 50}
              onClick={() => { changed(); setQuestions((qs) => [...qs, { uid: uid(), prompt: "", options: ["", ""], correct: 0 }]); }}>
        Add a question</button>

      <Problem error={action.error} />
      {saved && <div className="msg g" role="status">Draft saved.</div>}
      <button type="submit" className="btn" disabled={action.busy}>Save draft</button>
      {!active && <div className="small">Reactivate it to publish this version.</div>}
      {active && !ready && <div className="small">It needs a page and a question before it can be published.</div>}
      {active && (confirming ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm"><b>Publish version {draft.version}? Its pages and questions are frozen once it is, and everyone takes it from now.</b></span>
          <button type="button" className="btn primary" disabled={action.busy} onClick={() => void publish()}>Publish</button>
          <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>Cancel</button>
        </div>
      ) : (
        <button type="button" className="btn primary" disabled={action.busy || !ready} onClick={() => void publish()}>
          Publish version {draft.version}</button>
      ))}
    </form>
  );
}

/** Up, down and remove, for a page or a question. */
function Moves({ what, n, count, onMove, onRemove }: {
  what: string; n: number; count: number; onMove: (by: number) => void; onRemove: () => void;
}) {
  return (
    <span className="ml-auto flex gap-1">
      <button type="button" className="btn" disabled={n === 1} aria-label={`Move ${what} ${n} up`} onClick={() => onMove(-1)}>↑</button>
      <button type="button" className="btn" disabled={n === count} aria-label={`Move ${what} ${n} down`} onClick={() => onMove(1)}>↓</button>
      <button type="button" className="btn danger" aria-label={`Remove ${what} ${n}`} onClick={onRemove}>Remove</button>
    </span>
  );
}

function PageCard({ page, n, count, onChange, onMove, onRemove }: {
  page: Page; n: number; count: number; onChange: (c: Partial<Page>) => void; onMove: (by: number) => void; onRemove: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(file: File | undefined) {
    if (!file || !hasFile(page.kind)) return;
    setError(null);
    const { most } = FILES[page.kind];
    if (file.size > most) { setError(`That file is too big: the most is ${most / 1_000_000} MB.`); return; }
    setSending(true);
    try {
      const u = await api.upload(`page-${page.kind}`, file);
      onChange({ file: { id: u.id, content_type: u.content_type, size_bytes: u.size_bytes, link: null } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  return (
    <fieldset className="card flex flex-col gap-2" aria-label={`Page ${n}`}>
      <div className="flex items-center gap-2">
        <b className="text-sm">Page {n} · {kindLabel(page.kind)}</b>
        <Moves what="page" n={n} count={count} onMove={onMove} onRemove={onRemove} />
      </div>
      <label className="label">Title
        <input className="field" value={page.title} maxLength={120} onChange={(e) => onChange({ title: e.target.value })} required />
      </label>
      {page.kind === "text" && (
        <label className="label">Text
          <textarea className="field" style={{ height: 140 }} value={page.body} maxLength={20000}
                    onChange={(e) => onChange({ body: e.target.value })} required />
        </label>
      )}
      {hasFile(page.kind) && (
        <>
          <label className="label">File
            <input type="file" accept={FILES[page.kind].accept} disabled={sending}
                   onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          {sending && <div className="small" role="status">Sending…</div>}
          {page.file && !sending && <div className="small">{TYPES[page.file.content_type] ?? page.file.content_type} · {megabytes(page.file.size_bytes)}</div>}
          {page.file?.link && page.kind === "image" && <img src={page.file.link} alt={page.title} width={240} style={{ borderRadius: 10 }} />}
          {page.file?.link && page.kind === "video" && <video src={page.file.link} controls preload="metadata" width={320} />}
          {page.file?.link && page.kind === "pdf" && <a href={page.file.link} target="_blank" rel="noopener noreferrer">Save the PDF</a>}
          {error && <div className="msg r" role="alert">{error}</div>}
        </>
      )}
      {page.kind === "link" && (
        <label className="label">Web address
          <input className="field" type="url" value={page.url} maxLength={2000} placeholder="https://…"
                 onChange={(e) => onChange({ url: e.target.value })} required />
        </label>
      )}
      {page.kind !== "text" && (
        <label className="label">Words under it (optional)
          <input className="field" value={page.body} maxLength={2000} onChange={(e) => onChange({ body: e.target.value })} />
        </label>
      )}
    </fieldset>
  );
}

function QuestionCard({ question: q, n, count, onChange, onMove, onRemove }: {
  question: Ask; n: number; count: number; onChange: (c: Partial<Ask>) => void; onMove: (by: number) => void; onRemove: () => void;
}) {
  function drop(j: number) {
    const correct = q.correct === j ? 0 : q.correct > j ? q.correct - 1 : q.correct;
    onChange({ options: q.options.filter((_, k) => k !== j), correct });
  }

  return (
    <fieldset className="card flex flex-col gap-2" aria-label={`Question ${n}`}>
      <div className="flex items-center gap-2">
        <b className="text-sm">Question {n}</b>
        <Moves what="question" n={n} count={count} onMove={onMove} onRemove={onRemove} />
      </div>
      <label className="label">Question
        <input className="field" value={q.prompt} maxLength={500} onChange={(e) => onChange({ prompt: e.target.value })} required />
      </label>
      <div className="small">Mark the right answer.</div>
      {q.options.map((o, j) => (
        <div key={j} className="flex items-center gap-2">
          <input type="radio" name={`right-${q.uid}`} checked={q.correct === j} onChange={() => onChange({ correct: j })}
                 aria-label={`Answer ${j + 1} is the right one`} />
          <input className="field" value={o} maxLength={200} aria-label={`Answer ${j + 1}`} required
                 onChange={(e) => onChange({ options: q.options.map((x, k) => (k === j ? e.target.value : x)) })} />
          {q.options.length > 2 && (
            <button type="button" className="btn" aria-label={`Remove answer ${j + 1}`} onClick={() => drop(j)}>✕</button>
          )}
        </div>
      ))}
      {q.options.length < 6 && (
        <button type="button" className="btn" onClick={() => onChange({ options: [...q.options, ""] })}>Add an answer</button>
      )}
    </fieldset>
  );
}
