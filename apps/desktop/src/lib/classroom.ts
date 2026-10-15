/** The classroom, worked out from the matrix: a desk for each role, and the
 * people with that role sitting at it, each coloured by how current they
 * are; then where each desk and seat goes in the room. Pure, so it is
 * tested without drawing. */
import type { Matrix, MatrixRow } from "../api/types";
import { scr } from "./iso";
import type { Tone } from "./status";

/** The most people drawn at one desk; the rest are counted ("+12"). */
export const SEATS = 6;
/** A desk's size in the room's units (about 2 cm each): long enough for six. */
export const DESK = { w: 170, d: 36, h: 32 };
/** A seat's place along the desk, and how far apart they are. */
const SEAT_FIRST = 20;
export const SEAT_PITCH = 26;
/** How far behind the desk's back edge a chair stands (its middle). */
const SEAT_BACK = 9;
/** The role's sign: a low board standing on the floor in front of the
 * chairs, its face toward the viewer, clear of the chairs' legs. */
export const SIGN = { inset: 8, w: 154, h: 26, behind: 50 };
/** The tallest thing at a desk: a seated head with the mark over it. */
export const TALLEST = 86;
/** From one desk to the next across the room, and from row to row. */
export const PITCH_X = 240;
export const PITCH_Y = 150;
/** The front of the room, before the first row: the board and the teacher's desk. */
export const FRONT = 250;
const SIDE = 70;
const BACK = 10;
/** How high the walls are drawn, and how thick. */
export const WALL = 140;
export const WALL_T = 8;
const MARGIN = 24;
/** The picture is never drawn smaller than this many pixels a unit, so
 * labels stay readable and people stay big enough to click: a big room
 * scrolls instead. */
export const MIN_SCALE = 0.8;
/** A person's link: the size of a seated figure, head to seat. */
export const SEAT_LINK = { w: 20, h: 46 };

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

/** Desks across the room: three, until there are so many rows that a
 * wider room keeps it nearer square (30 roles is five across, six deep). */
export function columns(count: number): number {
  return Math.max(3, Math.ceil(Math.sqrt((count * PITCH_Y) / PITCH_X)));
}

/** Desk i's back corner on the floor, of `count`: row by row, front to back. */
export function deskAt(i: number, count: number): Spot {
  const cols = columns(count);
  return { x: SIDE + (i % cols) * PITCH_X, y: FRONT + Math.floor(i / cols) * PITCH_Y };
}

/** Seat k at a desk: a row of chairs behind it, facing the board; the
 * middle of the chair, on the floor. */
export function seatAt(desk: Spot, k: number): Spot {
  return { x: desk.x + SEAT_FIRST + k * SEAT_PITCH, y: desk.y + DESK.d + SEAT_BACK };
}

/** The sign's top left corner, on its face toward the viewer. */
export function signAt(desk: Spot): Spot & { z: number } {
  return { x: desk.x + SIGN.inset, y: desk.y + DESK.d + SIGN.behind, z: SIGN.h };
}

/** The room for this many desks: as wide as its columns, as deep as its rows. */
export function roomSize(count: number): { w: number; d: number } {
  const cols = columns(count);
  const rows = Math.max(1, Math.ceil(count / cols));
  return { w: SIDE * 2 + (cols - 1) * PITCH_X + DESK.w, d: FRONT + rows * PITCH_Y + BACK };
}

/** The teacher's desk, at the front in the middle, and its chair between it
 * and the board. */
export function teacherDesk(count: number): Spot & { w: number; d: number; h: number } {
  return { x: roomSize(count).w / 2 - 80, y: 100, w: 160, d: 50, h: 32 };
}

export interface Box3 { x0: number; x1: number; y0: number; y1: number; z0: number; z1: number }

/** Everything drawn for desk i, as boxes in the room: the desk, the
 * chairs with the people on them (to the top of the marks over their
 * heads), and the sign standing in front. */
export function deskParts(i: number, count: number): Box3[] {
  const at = deskAt(i, count);
  const sign = signAt(at);
  const first = seatAt(at, 0);
  const last = seatAt(at, SEATS - 1);
  return [
    { x0: at.x, x1: at.x + DESK.w, y0: at.y, y1: at.y + DESK.d, z0: 0, z1: DESK.h },
    { x0: first.x - 12, x1: last.x + 12, y0: first.y - 8, y1: first.y + 8, z0: 0, z1: TALLEST },
    { x0: sign.x, x1: sign.x + SIGN.w, y0: sign.y - 2, y1: sign.y, z0: 0, z1: SIGN.h },
  ];
}

/** The teacher's desk and chair, with what is on the desk. */
export function teacherVolume(count: number): Box3 {
  const t = teacherDesk(count);
  return { x0: t.x, x1: t.x + t.w, y0: t.y - 50, y1: t.y + t.d, z0: 0, z1: 60 };
}

/** The outline a box makes in the picture: the six corners of its hexagon. */
export function outline(b: Box3): [number, number][] {
  return [
    scr(b.x0, b.y0, b.z1), scr(b.x1, b.y0, b.z1), scr(b.x1, b.y0, b.z0),
    scr(b.x1, b.y1, b.z0), scr(b.x0, b.y1, b.z0), scr(b.x0, b.y1, b.z1),
  ];
}

/** The picture's viewBox for this many desks: the floor's corners and the
 * walls' tops, with a margin. */
export function viewBox(count: number): { x: number; y: number; w: number; h: number } {
  const { w, d } = roomSize(count);
  const left = scr(-WALL_T, d)[0];
  const right = scr(w, -WALL_T)[0];
  const top = scr(-WALL_T, -WALL_T, WALL)[1];
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

/** A length in the room's units as a share of the picture's width, for
 * CSS inside the room (a container): it scales with the picture. */
export function unitsWide(count: number, n: number): string {
  return `${Number(((n * 100) / viewBox(count).w).toFixed(3))}cqw`;
}

/** The narrowest the picture may be drawn, in pixels. */
export function minWidth(count: number): number {
  return Math.round(viewBox(count).w * MIN_SCALE);
}
