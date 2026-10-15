import { useCallback, useEffect, useRef, useState, type FormEvent, type RefObject } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Attempt, Module, ModulePage } from "../api/types";
import { useSession } from "../auth/Session";
import { useDing } from "../lib/sound";
import { Back, plain } from "../ui";

const CHANGED = "The module has changed: start the new version.";
// how often a playing video says someone is still here
const STILL_HERE_MS = 60_000;

/** A module, one page at a time, then the quiz. Where the learner is goes
 * to the API as they go, so they carry on where they left off, on this
 * device or another; nothing of theirs is kept on a shared tablet. */
export function ModulePlayer() {
  const { key = "" } = useParams();
  const [module, setModule] = useState<Module | null>(null);
  const [at, setAt] = useState(0);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const top = useRef<HTMLHeadingElement>(null);
  // the heading of the page (or the quiz) on show: focus goes there on a move
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  // one place saved at a time; taps while one is on its way keep only the last
  const saving = useRef(false);
  const wanted = useRef<{ version: number; page: number } | null>(null);
  const path = `/v1/modules/${encodeURIComponent(key)}`;

  /** Fetch the module; `keepPlace` stays on the page on show (fresh links
   * for the same pages), otherwise it opens where they left off. */
  const load = useCallback(async (keepPlace = false) => {
    setTrouble(null);
    try {
      const m = await api.get<Module>(path);
      setModule(m);
      if (!keepPlace) setAt(m.resume_at);
    } catch (e) {
      setTrouble(e instanceof ApiError && e.status === 404 ? "There's nothing to do here yet. Ask your manager." : plain(e));
    }
  }, [path]);

  useEffect(() => { void load(); }, [load]);

  // the button they pressed went with the old page: take focus to the new one
  useEffect(() => {
    if (!moved.current) return;
    moved.current = false;
    heading.current?.focus({ preventScroll: true });
  }, [at]);

  /** A newer version came out while they read: it starts from the top. */
  const changed = useCallback(async () => {
    setNotice(CHANGED);
    await load();
  }, [load]);

  /** Go to a page (one past the last is the quiz) and keep the place. A
   * place that doesn't save only means opening a page earlier next time. */
  function go(page: number) {
    if (!module) return;
    setNotice(null);
    moved.current = true;
    setAt(page);
    // a long page was scrolled down: the next one starts at its top
    top.current?.scrollIntoView?.({ block: "start" });
    wanted.current = { version: module.version.version, page };
    void save();
  }

  /** Sends the latest place, after any still on its way, so an earlier tap
   * never lands last. */
  async function save() {
    if (saving.current) return;
    saving.current = true;
    try {
      while (wanted.current) {
        const place = wanted.current;
        wanted.current = null;
        try {
          await api.put(`${path}/progress`, place);
        } catch (e) {
          if (e instanceof ApiError && e.code === "new_version") {
            wanted.current = null;
            void changed();
          }
        }
      }
    } finally {
      saving.current = false;
    }
  }

  const pages = module?.version.pages ?? [];
  return (
    <main className="screen">
      <Back />
      {trouble && <div className="msg r" role="alert">{trouble}</div>}
      {!module && !trouble && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {module && (
        <>
          <h1 ref={top} style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{module.name}</h1>
          {notice && <div className="msg r" role="alert">{notice}</div>}
          {at < pages.length ? (
            <PageView key={at} page={pages[at]} n={at + 1} count={pages.length} heading={heading}
                      onBack={() => go(at - 1)} onNext={() => go(at + 1)} onReload={() => void load(true)} />
          ) : (
            <Quiz key={module.version.id} module={module} path={path} heading={heading} onChanged={changed}
                  onBack={() => go(pages.length - 1)} onReadAgain={() => go(0)} />
          )}
        </>
      )}
    </main>
  );
}

function PageView({ page, n, count, heading, onBack, onNext, onReload }: {
  page: ModulePage; n: number; count: number; heading: RefObject<HTMLHeadingElement | null>;
  onBack: () => void; onNext: () => void; onReload: () => void;
}) {
  return (
    <>
      <div className="steps" aria-label={`Page ${n} of ${count}`}>
        <span>Page {n} of {count}</span>
        <span className="bar"><span style={{ width: `${(n / (count + 1)) * 100}%` }} /></span>
      </div>
      <h2 ref={heading} tabIndex={-1} className="pagetitle">{page.title}</h2>
      {page.kind === "text" && <article className="policy" aria-label={page.title}>{page.body}</article>}
      {page.kind === "image" && page.file && <Picture key={page.file.link} link={page.file.link} title={page.title} onReload={onReload} />}
      {page.kind === "video" && page.file && <Video link={page.file.link} title={page.title} />}
      {page.kind === "pdf" && page.file && (
        <a className="big ghost as-button" href={page.file.link} target="_blank" rel="noopener noreferrer">
          Open the PDF<span className="sr-only"> (downloads the PDF)</span></a>
      )}
      {page.kind === "link" && page.url && (
        <a className="big ghost as-button" href={page.url} target="_blank" rel="noopener noreferrer">
          Open {page.title}<span className="sr-only"> (opens in a new tab)</span></a>
      )}
      {page.kind !== "text" && page.body && <p className="caption">{page.body}</p>}
      <div className="pair">
        {n > 1 && <button type="button" className="big ghost" onClick={onBack}>Back</button>}
        <button type="button" className="big primary" onClick={onNext}>{n === count ? "Start the quiz" : "Next"}</button>
      </div>
    </>
  );
}

/** Its signed link runs out after a while: loading the module again gets a
 * fresh one. */
function Picture({ link, title, onReload }: { link: string; title: string; onReload: () => void }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div className="msg r" role="alert">
        The picture couldn't be shown.{" "}
        <button type="button" className="link" onClick={onReload}>Load it again</button>
      </div>
    );
  }
  return <img className="pageimg" src={link} alt={title} onError={() => setFailed(true)} />;
}

/** Played as it was uploaded; the phone seeks it with Range requests. While
 * it plays, nobody taps, so it tells the session someone is still here. */
function Video({ link, title }: { link: string; title: string }) {
  const { stillHere } = useSession();
  const last = useRef(Date.now());
  const [failed, setFailed] = useState(false);

  function playing() {
    if (Date.now() - last.current < STILL_HERE_MS) return;
    last.current = Date.now();
    stillHere();
  }

  if (failed) return <div className="msg r" role="alert">The video couldn't be played. Go back to My training and open the module again.</div>;
  return <video className="pagevideo" src={link} controls playsInline preload="metadata" aria-label={title}
                onTimeUpdate={playing} onError={() => setFailed(true)} />;
}

function Quiz({ module, path, heading, onChanged, onBack, onReadAgain }: {
  module: Module; path: string; heading: RefObject<HTMLHeadingElement | null>;
  onChanged: () => Promise<void>; onBack: () => void; onReadAgain: () => void;
}) {
  const { questions, pass_mark: passMark, version } = module.version;
  const none = () => questions.map(() => null as number | null);
  const [answers, setAnswers] = useState(none);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Attempt | null>(null);
  // after three goes in a row that didn't pass, when they may try again
  const [retryAt, setRetryAt] = useState<string | null>(() => waiting(module.retry_at));
  // the form goes when the result comes (and back on another go), taking
  // focus with it: it goes to the result, so it is read out, or the quiz's top
  const said = useRef<HTMLElement>(null);
  const again = useRef(false);
  const { wake, ding } = useDing();

  useEffect(() => {
    if (result || retryAt) said.current?.focus();
    else if (again.current) { again.current = false; heading.current?.focus(); }
  }, [result, retryAt, heading]);

  // the wait is over: the quiz again (a timer can't wait longer than about 24 days)
  useEffect(() => {
    if (!retryAt) return;
    const timer = setTimeout(() => setRetryAt(null),
      Math.min(Math.max(new Date(retryAt).getTime() - Date.now(), 0), 2 ** 31 - 1));
    return () => clearTimeout(timer);
  }, [retryAt]);

  async function handIn(e: FormEvent) {
    e.preventDefault();
    wake();
    setBusy(true);
    setError(null);
    try {
      const attempt = await api.post<Attempt>(`${path}/attempts`, { version, answers });
      if (attempt.passed) ding();
      setResult(attempt);
    } catch (err) {
      const until = err instanceof ApiError && err.code === "cooldown"
        ? waiting((err.body as { retry_at?: unknown })?.retry_at) : null;
      if (err instanceof ApiError && err.code === "new_version") await onChanged();
      else if (until) setRetryAt(until);
      else setError(plain(err));
    } finally {
      setBusy(false);
    }
  }

  if (result?.passed) {
    return (
      <>
        <section ref={said} tabIndex={-1} className="ding" role="status" aria-label="Passed">
          <b>Ding!</b>
          <span>You passed {module.name} with {result.score}%.</span>
        </section>
        <Link to="/" className="big primary as-button">Back to My training</Link>
      </>
    );
  }
  if (retryAt) {
    return (
      <>
        <section ref={said} tabIndex={-1} className="miss" role="status" aria-label="Wait to try again">
          <span>Three tries in a row didn't pass. You can try again after {when(retryAt)}.</span>
        </section>
        <button type="button" className="big ghost" onClick={onReadAgain}>Read it again</button>
      </>
    );
  }
  if (result) {
    return (
      <>
        <section ref={said} tabIndex={-1} className="miss" role="status" aria-label="Not passed">
          <b>{result.score}%</b>
          <span>Not this time: you need {result.pass_mark}% to pass. Read it again, or have another go.</span>
        </section>
        <button type="button" className="big primary" onClick={() => { again.current = true; setResult(null); setAnswers(none()); }}>Try again</button>
        <button type="button" className="big ghost" onClick={onReadAgain}>Read it again</button>
      </>
    );
  }
  return (
    <form onSubmit={handIn} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h2 ref={heading} tabIndex={-1} className="pagetitle">The quiz</h2>
      <div className="small" style={{ color: "var(--color-muted)" }}>
        {questions.length} {questions.length === 1 ? "question" : "questions"}. You need {passMark}% to pass, and you can try again.</div>
      {questions.map((q, i) => (
        <fieldset key={i} className="question">
          <legend>{i + 1}. {q.prompt}</legend>
          {q.options.map((o, j) => (
            <label key={j} className="choice">
              <input type="radio" name={`question-${i}`} checked={answers[i] === j}
                     onChange={() => setAnswers((a) => a.map((x, k) => (k === i ? j : x)))} />
              {o}
            </label>
          ))}
        </fieldset>
      ))}
      {error && <div className="msg r" role="alert">{error}</div>}
      <button type="submit" className="big primary" disabled={busy || answers.some((a) => a === null)}>Hand it in</button>
      <button type="button" className="link" onClick={onBack}>Back to the pages</button>
    </form>
  );
}

/** The time, if it is still to come. */
function waiting(at: unknown): string | null {
  return typeof at === "string" && new Date(at).getTime() > Date.now() ? at : null;
}

/** A time as people say it: 2:15 pm, and the day too when it isn't today. */
function when(at: string): string {
  const d = new Date(at);
  const time = d.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" });
  if (d.toDateString() === new Date().toDateString()) return time;
  return `${time} on ${d.toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" })}`;
}
