import { Link } from "react-router-dom";
import { ApiError } from "./api/client";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 7 15 10V28L3 25Z" fill="#5B93D6" />
      <path d="M29 7 17 10V28L29 25Z" fill="#2F6FB8" />
      <path d="M19.5 17.5 22 20l4.5-6" fill="none" stroke="#E8F0FA" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const SOMETHING = "Something went wrong. Try again.";
const REFUSED = "That didn't work. Try again, or ask your manager.";
const NOT_ANSWERING = "Simple LMS isn't answering right now. Try again in a moment.";

/** A sentence: a capital first, one full stop (or ? or !) at the end. */
function sentence(words: string): string {
  const s = words.trim().replace(/\.+$/, "");
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1) + (/[?!]$/.test(s) ? "" : ".");
}

/** What went wrong, in plain words: never "Simple LMS answered 500". A field
 * error says what the field needs; an answer with no reason, or anything else
 * thrown, gets a plain sentence of its own. */
export function plain(e: unknown): string {
  if (!(e instanceof ApiError)) return (e instanceof Error && sentence(e.message)) || SOMETHING;
  if (e.status >= 500) return NOT_ANSWERING;
  const first = e.errors[0];
  if (first) return sentence(first.message) || REFUSED;
  // no detail and no errors: the client's own "Simple LMS answered 4xx"
  if (e.message === `Simple LMS answered ${e.status}`) return REFUSED;
  return sentence(e.message) || REFUSED;
}

/** The top of a screen reached from My training, with the way back. */
export function Back() {
  return (
    <div className="top"><Logo /><Link to="/" className="chip" style={{ marginLeft: "auto", textDecoration: "none" }}>Back to My training</Link></div>
  );
}
