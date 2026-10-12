/** How a status looks: green, amber, red or grey, with words for it. */
import type { Cell, Status } from "../api/types";

export type Tone = "green" | "amber" | "red" | "grey";

export const LOOK: Record<Status, { label: string; short: string; tone: Tone }> = {
  current: { label: "Current", short: "✓", tone: "green" },
  expiring: { label: "Expiring", short: "!", tone: "amber" },
  lapsed: { label: "Lapsed", short: "✕", tone: "red" },
  missing: { label: "Missing", short: "–", tone: "red" },
  waived: { label: "Waived", short: "W", tone: "grey" },
  not_required: { label: "Not required", short: "", tone: "grey" },
};

export const STATUSES = Object.keys(LOOK) as Status[];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-01" → "1 Nov 2026", day first as Australians write it, the
 * same in every browser. */
export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** What a cell's tooltip and the history drawer say about it. */
export function describe(cell: Cell): string {
  const { label } = LOOK[cell.status];
  switch (cell.status) {
    case "current":
      return cell.expires_on ? `${label} until ${formatDate(cell.expires_on)}` : `${label}, doesn't run out`;
    case "expiring":
      return `${label}: good until ${formatDate(cell.expires_on)}`;
    case "lapsed":
      return `${label}: was good until ${formatDate(cell.expires_on)}`;
    default:
      return label;
  }
}
