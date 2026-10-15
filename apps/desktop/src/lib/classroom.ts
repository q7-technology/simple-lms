/** The classroom, worked out from the matrix: a desk for each role, and the
 * people with that role sitting at it, each coloured by how current they
 * are; then where each desk and seat goes in the room. Pure, so it is
 * tested without drawing. */
import type { Matrix, MatrixRow } from "../api/types";
import { scr } from "./iso";
import type { Tone } from "./status";

/** The most people drawn at one desk; the rest are counted ("+12"). */
export const SEATS = 6;
/** Desks in a row across the room; more roles make more rows. */
export const COLS = 3;
/** A desk's size in the room's units, as Simple WMS's pallets are. */
export const DESK = { w: 150, d: 50, h: 34 };
const PITCH_X = 210;
const PITCH_Y = 170;
/** The front of the room, before the first row: the board and the teacher's desk. */
export const FRONT = 200;
const SIDE = 40;
/** How high the walls are drawn. */
export const WALL = 120;
const MARGIN = 24;

export interface Figure { code: string; name: string; tone: Tone }

export interface Desk {
  /** the role's key */
  key: string;
  name: string;
  /** everyone with the role, those who need a look first, then by name */
  people: Figure[];
  tally: Record<Tone, number>;
}

export interface Spot { x: number; y: number }

/** What each colour means, in the classroom's words. */
export const TONE_WORDS: Record<Tone, string> = {
  red: "need training", amber: "expiring", green: "current", grey: "nothing due",
};

const WORST_FIRST: Tone[] = ["red", "amber", "green", "grey"];

/** How current a person is, all told: red if anything asked of them has
 * lapsed or is missing, amber if something runs out within 30 days, green
 * if the rest is current, grey if nothing is asked (or it is all waived). */
export function personTone(row: MatrixRow): Tone {
  const statuses = Object.values(row.cells).map((c) => c.status);
  if (statuses.some((s) => s === "lapsed" || s === "missing")) return "red";
  if (statuses.includes("expiring")) return "amber";
  if (statuses.includes("current")) return "green";
  return "grey";
}

/** How many of each colour. */
export function tally(people: Figure[]): Record<Tone, number> {
  const t: Record<Tone, number> = { red: 0, amber: 0, green: 0, grey: 0 };
  for (const p of people) t[p.tone] += 1;
  return t;
}

/** "3 current, 1 expiring": the colours there are. */
export function tallyWords(t: Record<Tone, number>): string {
  return (["green", "amber", "red", "grey"] as Tone[])
    .filter((tone) => t[tone] > 0).map((tone) => `${t[tone]} ${TONE_WORDS[tone]}`).join(", ");
}

const byConcern = (a: Figure, b: Figure) =>
  WORST_FIRST.indexOf(a.tone) - WORST_FIRST.indexOf(b.tone) || a.name.localeCompare(b.name) || a.code.localeCompare(b.code);

const figure = (row: MatrixRow): Figure => ({ code: row.code, name: row.name, tone: personTone(row) });

/** A desk for every role someone in view has, by name; a person with two
 * roles sits at both. Deactivated people aren't in the matrix, so they
 * aren't here, and nobody without a role sits down (see `unseated`). */
export function desks(matrix: Matrix): Desk[] {
  const roles = new Map<string, { name: string; people: Figure[] }>();
  for (const row of matrix.people) {
    for (const r of row.roles) {
      const at = roles.get(r.key) ?? { name: r.name, people: [] };
      at.people.push(figure(row));
      roles.set(r.key, at);
    }
  }
  return [...roles.entries()]
    .map(([key, r]) => {
      const people = [...r.people].sort(byConcern);
      return { key, name: r.name, people, tally: tally(people) };
    })
    .sort((a, b) => a.name.localeCompare(b.name) || a.key.localeCompare(b.key));
}

/** Those in view with no role yet: no desk, so they don't sit down. */
export function unseated(matrix: Matrix): Figure[] {
  return matrix.people.filter((row) => row.roles.length === 0).map(figure).sort(byConcern);
}

/** Everyone in view once, however many roles they have. */
export function everyone(matrix: Matrix): Record<Tone, number> {
  return tally(matrix.people.map(figure));
}

/** Desk i's corner on the floor: three to a row, front to back. */
export function deskAt(i: number): Spot {
  return { x: SIDE + (i % COLS) * PITCH_X, y: FRONT + Math.floor(i / COLS) * PITCH_Y };
}

/** Seat k at a desk: a row of chairs behind it, facing the board. */
export function seatAt(desk: Spot, k: number): Spot {
  return { x: desk.x + 15 + k * 24, y: desk.y + DESK.d + 22 };
}

/** The room for this many desks: always three wide, as deep as its rows. */
export function roomSize(count: number): { w: number; d: number } {
  const rows = Math.max(1, Math.ceil(count / COLS));
  return { w: SIDE * 2 + (COLS - 1) * PITCH_X + DESK.w, d: FRONT + rows * PITCH_Y };
}

/** The picture's viewBox for this many desks: the floor's corners and the
 * walls' tops, with a margin. */
export function viewBox(count: number): { x: number; y: number; w: number; h: number } {
  const { w, d } = roomSize(count);
  const left = scr(0, d)[0];
  const right = scr(w, 0)[0];
  const top = scr(0, 0, WALL)[1];
  const bottom = scr(w, d)[1];
  return { x: left - MARGIN, y: top - MARGIN, w: right - left + 2 * MARGIN, h: bottom - top + 2 * MARGIN };
}

/** Where a point of the room is over the picture, in percent, for a link
 * laid over it (as Simple TMS lays its trucks over the region). */
export function over(count: number, x: number, y: number, z = 0): { left: string; top: string } {
  const box = viewBox(count);
  const [px, py] = scr(x, y, z);
  const pc = (v: number) => `${Number(v.toFixed(2))}%`;
  return { left: pc(((px - box.x) / box.w) * 100), top: pc(((py - box.y) / box.h) * 100) };
}
