/** My training in three parts, the way the learner reads it. */
import type { TrainingItem } from "../api/types";

export interface Groups {
  /** lapsed or never done: oldest lapse first, then the missing by name */
  overdue: TrainingItem[];
  /** expiring within 30 days: soonest first */
  dueSoon: TrainingItem[];
  /** current: by name */
  done: TrainingItem[];
}

const byName = (a: TrainingItem, b: TrainingItem) => a.name.localeCompare(b.name);
const byExpiry = (a: TrainingItem, b: TrainingItem) =>
  (a.expires_on ?? "").localeCompare(b.expires_on ?? "") || byName(a, b);

export function groupTraining(items: TrainingItem[]): Groups {
  const lapsed = items.filter((i) => i.status === "lapsed").sort(byExpiry);
  const missing = items.filter((i) => i.status === "missing").sort(byName);
  return {
    overdue: [...lapsed, ...missing],
    dueSoon: items.filter((i) => i.status === "expiring").sort(byExpiry),
    done: items.filter((i) => i.status === "current").sort(byName),
  };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** The line under each item's name. */
export function whenLine(item: TrainingItem): string {
  switch (item.status) {
    case "lapsed":
      return `Ran out after ${formatDate(item.expires_on)}`;
    case "missing":
      return "Not done yet";
    case "expiring":
      return `Due by ${formatDate(item.expires_on)}`;
    case "current":
      return item.expires_on ? `Done · good until ${formatDate(item.expires_on)}` : "Done · doesn't run out";
  }
}

export type Step = { to: string; label: string } | { waiting: string } | null;

/** What the learner can do about an item here: do a module or sign a
 * policy that isn't current, or send in a ticket that is missing, running
 * out or run out. A ticket already sent in waits for a manager; a practical
 * waits for their supervisor to watch them do it. */
export function nextStep(item: TrainingItem): Step {
  const key = encodeURIComponent(item.key);
  if (item.kind === "practical" && item.status !== "current") return { waiting: "Your supervisor signs this off with you" };
  if (item.kind === "module" && item.status !== "current") return { to: `/module/${key}`, label: "Start the module" };
  if (item.kind === "policy" && item.status !== "current") return { to: `/sign/${key}`, label: "Read and sign" };
  if (item.kind === "ticket") {
    if (item.waiting) return { waiting: "Sent in · waiting for a manager's check" };
    if (item.status !== "current") return { to: `/ticket/${key}`, label: "Add your ticket" };
  }
  return null;
}
