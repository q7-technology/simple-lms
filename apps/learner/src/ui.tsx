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

/** What went wrong, in plain words: never "Simple LMS answered 500". A field
 * error says what the field needs. */
export function plain(e: unknown): string {
  if (!(e instanceof ApiError)) return (e as Error).message;
  if (e.status >= 500) return "Simple LMS isn't answering right now. Try again in a moment.";
  const first = e.errors[0];
  if (first) return first.message.charAt(0).toUpperCase() + first.message.slice(1) + ".";
  return e.message.charAt(0).toUpperCase() + e.message.slice(1) + ".";
}

/** The top of a screen reached from My training, with the way back. */
export function Back() {
  return (
    <div className="top"><Logo /><Link to="/" className="chip" style={{ marginLeft: "auto", textDecoration: "none" }}>Back to My training</Link></div>
  );
}
