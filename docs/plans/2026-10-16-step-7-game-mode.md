# Simple LMS step 7: Game Mode — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build step 7 of `docs/plans/2026-10-12-simple-lms-design.md`: Game Mode, the look Simple LMS shares with its siblings. The desktop opens on a **classroom** drawn in the same isometric view as Simple WMS and Simple TMS: the board and the teacher's desk at the front, then a desk for each role, labelled with its name, and the people with that role sitting at it, each a figure coloured by how current they are. Clicking a desk opens the matrix at that role; clicking a person opens them in People. Every screen (the matrix, People, Roles, Competencies, Inbox, and whatever steps 4 to 6 added) opens as a drawer over the classroom, as in Simple WMS, and the matrix is always one click away in the bar along the top. The learner app works like the scanner: big buttons, a ring on My training for "3 of 5 done", and a "Ding!" out loud on a pass. Game touches are each viewer's own, kept in the browser and never on the server, and off in one click. Usable end to end: Mel signs in and sees the Picker desk with Kim sitting first, red with a "!" over her head; clicks the desk and the matrix opens over the classroom at the Picker role; Kim passes the induction on her phone, which dings; Mel goes back to the classroom and Kim is green.

**Architecture:** Front end only. `apps/desktop/src/lib/iso.ts` is Simple WMS's isometric projection (`TOP`, `LEFT`, `RIGHT` face transforms and `scr()`, from its `scripts/warehouse_layers.py`). `lib/classroom.ts` works the classroom out from the matrix the desktop already loads (`GET /v1/matrix`): the desks, who sits where, how current each is, where each desk and seat goes on the floor, and the picture's size; pure functions, tested without drawing. `ui/ClassroomArt.tsx` draws it as inline SVG, boxes and figures sorted back to front as Simple WMS sorts its pallets. `pages/Classroom.tsx` lays real links over the picture, positioned in percent of it, as Simple TMS lays its truck buttons over its region: one per desk (to `/matrix?role=…`) and one per person seated (to `/people?person=…`). `ui/Layout.tsx` keeps the bar along the top; in Game Mode it draws the classroom at `/` and every other route inside `ui/ScreenPanel.tsx`, a drawer over the empty classroom, named from one list of screens (`ui/screens.ts`) that the bar is drawn from too. The matrix moves to `/matrix`; `/` without Game Mode goes there, as the desktop did before. Each viewer's switch is `lms.game` in localStorage (`lib/gamePrefs.ts`, after Simple WMS's). The learner app gains `lib/game.ts` (`lms.learner.game`: sound on or off on this device), `lib/sound.ts` (a two-note ding made with WebAudio, as Simple WMS's is), a `Ring` on My training, and a Sound switch beside Sign out. No API change, no migration, no new dependency.

**Tech Stack:** as step 3: Vite 6, React 19, TypeScript 5, Tailwind 4, Vitest 3 with Testing Library. No new dependencies: the drawing is inline SVG with Simple WMS's face transforms, the sound is WebAudio, and the switches are `useSyncExternalStore` over localStorage.

---

## Context

The design is settled; this plan does not change any of its decisions. It does what the design's "Look: Game Mode, like its siblings" says (as `main` has it since "Make Game Mode an isometric classroom, a desk for each role"), and its "Until step 7 the desktop opens on the matrix": with Game Mode on it opens on the classroom, and with it off it still opens on the matrix. The decisions in the step 1 to step 6 plans' Contexts still hold, and the code on `main` is the truth where it went further than those plans: the desktop's `Drawer` (focus moves in, stays in, goes back; `focus="dialog"`; `useCloseGuard`), `useLoad`/`useAction`, `LOOK` and the status tones, `.rowbtn` rows, the learner app's shared-tab sessions and idle wipe, `plain()`, and the Ding! words already on a pass and a signature.

Steps 4 to 6 come before this one and add screens: **Sign off** for supervisors (step 4), **Settings** (sign-in methods, SMTP, reminder days) and **webhooks and API keys** (step 6), each a route in `App.tsx` and a link in `Layout.tsx`'s bar. Game Mode wraps whatever screens exist then, without knowing them: every route other than `/` opens in the same drawer, named from `ui/screens.ts`. Task 3 moves the bar's links into that list; where your base has more links than the five on the step 3 tip, it says how to add each as one line. Nothing else in this plan depends on what steps 4 to 6 did, beyond the test counts (see Before you start).

### Decisions this plan makes that the design leaves open

- **The data is the matrix, as it is.** The classroom loads `GET /v1/matrix` with no filters: active people, by name, each with their roles and a cell for everything anyone in view is asked for; a supervisor gets their own team, as on the matrix screen. Nothing in the API changes: the matrix already says who has which role and how current they are, worked out by `status.py` (rule 2), and a second endpoint would be a second place to say it. One request each time the classroom is shown, which is also how it stays fresh: it loads again whenever a drawer closes, so a change made in one shows at once, and nothing polls in the background.
- **The view is Simple WMS's, copied, not imitated.** `lib/iso.ts` is its projection line for line (x runs down to the right at (0.866, 0.5), y down to the left at (−0.866, 0.5), z straight up), and a box is three rects in their faces' own coordinates under `TOP`, `LEFT` and `RIGHT` transforms, as `warehouse_layers.py` draws pallets and trucks. The difference is that the warehouse is one fixed picture generated by a script, and a classroom changes with the roles, so it is drawn by React from the same functions. Things are painted back to front by `x + y`, as the script sorts its items. No canvas, no game engine, no zoom or pan.
- **The room:** the board on the front wall (`y = 0`) and the teacher's desk before it, then the desks in rows of three, front to back, in role-name order (then key): desk `i` is at column `i % 3`, row `⌊i / 3⌋`. The room is always three desks wide and as deep as its rows, so any number of roles just makes it deeper (40 roles is 14 rows): the picture keeps its width and grows down, and the classroom scrolls. The SVG's `viewBox` is worked out from the floor's corners and the walls' tops (`viewBox()`), so nothing is cut off at any count. No positions are stored or dragged (YAGNI).
- **Who sits where:** everyone with a role sits at that role's desk, so someone with two roles sits at both, in the same colour. Nobody without a role sits down, as the design says: they get no figure, and the line under the heading counts them ("1 person has no role yet, so no desk. Give them one under People"). Deactivated people aren't in the matrix, so they aren't in the classroom. A role nobody in view has (a new one, or one outside a supervisor's team) has no desk; Roles lists them all.
- **A person's colour is the worst of what is asked of them** (`personTone`): red if anything has lapsed or is missing, amber if something runs out within 30 days, green if the rest is current, grey if nothing is asked or all of it is waived. Their colour, not their role's: an extra required of them alone counts too, and the matrix (one click on the desk) shows which competency it is. Red figures also carry a "!" and hop now and then, so colour is never the only sign.
- **Hundreds of people:** a desk seats six (a row of chairs behind it, facing the board), those who need a look first (red, amber, green, grey, then by name), and its label counts the rest ("Picker +12"); the link's name counts everyone ("Picker: 18 people, 14 current, 2 expiring, 2 need training. Open in the matrix"). So the page holds at most six figures and seven links per role, whatever the headcount, and working it out is one pass over the rows (`useMemo`). The heading line counts each person once, however many roles they have. The matrix response is the one the matrix screen already fetches.
- **Clicks:** a desk's label is a link to `/matrix?role=<key>`, which opens the matrix in its drawer with that role chosen (the matrix reads `role` from the address once, as it opens). Each person seated is a link to `/people?person=<code>`, which opens People in its drawer with their drawer open (People reads `person` the same way). The links are real `<a>` elements laid over the picture at the desk's and the seat's place (`over()`, percent of the picture), as Simple TMS lays its truck buttons over `region.svg`, not shapes inside the SVG, so they are focusable, named and clickable in every browser. A viewer who can't open People (a supervisor) gets the desks without the people links.
- **Every screen is a drawer over the classroom,** driven by the address as in Simple WMS and Simple TMS: `/` is the classroom, any other route is drawn in `ScreenPanel` over `ClassroomBackdrop` (the room with empty desks: no names, no data). The drawer is a labelled region (`<section aria-label="People">`), **not** a modal dialog: the bar along the top stays usable, so the matrix and every other screen are one click away from anywhere, and a screen's own drawers (a person, a role, a cell's history) stay the modal dialogs they are, over everything. ✕, the dim and Escape go back to the classroom. Escape belongs to an open dialog first (the panel listens on the document, a `Drawer` on the window, so the panel hears it first and stands aside while `[aria-modal="true"]` is open) and to a field being typed in, as `escapeBelongsElsewhere()` does in Simple WMS. Focus starts on ✕ ("Back to the classroom"); on the way back it goes to the desk or person that opened the drawer, or the classroom's heading (`ui/focusReturn.ts`, after Simple WMS's). The drawer slides in with no transform left at the end, so a fixed `Drawer` inside it is still placed against the window.
- **One list of screens:** `ui/screens.ts` holds each screen's path, label and the scope that shows it. The bar and the drawer's title both come from it, so they never disagree; a screen a later step adds is a line there and its route in `App.tsx`.
- **The Game Mode switch** is a button in the bar (`aria-pressed`). Off, the desktop is exactly as it was before this step: the matrix first, each screen a page under the bar, no classroom. It is each viewer's own: `lms.game` in localStorage, `{"classroom": true}` until they turn it off, read once and kept in memory (`useSyncExternalStore`, as Simple WMS's `gamePrefs.ts`). Every read and write is in try/catch: in a private window, or with storage blocked, it still switches for that visit. Never sent to the API.
- **Accessibility: the classroom is decorative-plus.** Everything it offers is on the matrix and the screens, reachable from the bar without it, and Game Mode turns off in one click. The picture is `aria-hidden` SVG; the links over it carry the words: each desk's says its role, headcount and colours in full, each person's says their name and colour, and they are grouped in lists ("Desks", "At the Picker desk"). The key names each colour in words. Motion is two small things in CSS only (a red figure's hop, the drawer sliding in), both off under `prefers-reduced-motion: reduce`. No timers.
- **The learner app's ring:** "3 of 5 done" over the three parts of My training, where done is what is current and the whole is everything My training lists (what they are asked for and not let off). The words say it all; the ring is the picture of it (`aria-hidden`), blue as it fills and green with a tick when everything is done. It is information, not a game touch, so it always shows. The big buttons are the learner app's already.
- **The ding:** the two notes Simple WMS plays when an order ships, made with WebAudio on the spot (no sound file to ship, cache or licence), when a module's quiz is passed and when a policy is signed: the two screens that already say "Ding!". Not on a fail, nor a ticket sent in (it waits for a manager). A phone only plays sound a tap started, so the tap on **Hand it in** or **Sign** wakes the audio, and the ding sounds when the answer comes. A browser without WebAudio just doesn't ding.
- **The learner app's switch is per device, not per person:** a **Sound** chip beside Sign out on My training (`aria-pressed`), kept as `lms.learner.game`. On a shared tablet the tablet's sound is the tablet's business, and a setting that names nobody is never wiped with a session (the session's storage listener only listens to its own key). Off, nothing plays and nothing wakes the audio; the Ding! words still show.
- **No static drawn screens this time.** Simple TMS drew `design/screens/` before its code; here the picture is drawn by code from the matrix, and a static copy would be a second drawing to keep in step. The walkthrough (Task 8) is where the look is checked.
- **Left out (YAGNI):** sound on the desktop, day and night, zoom and pan, dragging desks, chairs and other furniture beyond the board and the teacher's desk, a figure for those without a role, streaks and daily goals, polling, anything stored on the server.

---

## Before you start

```
cd "/Users/leightonlauton/Q7 Technology/Software/q7/simple-lms"
git switch main && git pull --ff-only
git switch -c step-7-game-mode
(cd apps/desktop && npm ci)
(cd apps/learner && npm ci)
(cd apps/desktop && npm test)
(cd apps/learner && npm test)
```

`npm` commands run from the app's folder. This step changes neither the API nor the database, so the API suite only has to pass as it did (Task 7). On the step 3 tip the app suites are at `Tests  60 passed (60)` (desktop) and `Tests  61 passed (61)` (learner). Steps 4 to 6 add tests of their own: write down what `npm test` says now in each app, and call the difference from 60 **D** and from 61 **L**. Every count below is the step 3 tip's plus this step's, so add D (desktop) or L (learner) to each before comparing.

---

### Task 1: The classroom worked out from the matrix, in Simple WMS's isometric view, and Game Mode kept for each viewer

**Files:**
- Create: `apps/desktop/src/lib/iso.ts`, `apps/desktop/src/lib/classroom.ts`, `apps/desktop/src/lib/gamePrefs.ts`
- Modify: `apps/desktop/src/test/setup.ts`
- Test: create `apps/desktop/src/test/classroom.test.ts`

**Step 1: Write the failing tests**

`apps/desktop/src/test/classroom.test.ts`:
```ts
import type { Cell, Matrix, MatrixRow, Status } from "../api/types";
import { COLS, FRONT, deskAt, desks, everyone, over, personTone, roomSize, seatAt, tallyWords, unseated, viewBox } from "../lib/classroom";
import { GAME_PREFS_KEY, getGamePrefs, reloadGamePrefs, setGamePrefs } from "../lib/gamePrefs";
import { scr } from "../lib/iso";

const cell = (status: Status): Cell => ({ status, granted_on: null, expires_on: null });
const PICKER = { key: "picker", name: "Picker" };
const FORKLIFT = { key: "forklift-operator", name: "Forklift operator" };

function row(code: string, name: string, roles: { key: string; name: string }[], ...statuses: Status[]): MatrixRow {
  return { code, name, roles, supervisor: null, cells: Object.fromEntries(statuses.map((s, i) => [`c${i}`, cell(s)])) };
}

const room = (...people: MatrixRow[]): Matrix => ({ today: "2026-10-12", competencies: [], people });

describe("a person's colour in the classroom", () => {
  it("is the worst of what is asked of them", () => {
    expect(personTone(row("A", "A", [], "current", "lapsed", "expiring"))).toBe("red");
    expect(personTone(row("A", "A", [], "current", "missing"))).toBe("red");
    expect(personTone(row("A", "A", [], "current", "expiring", "waived"))).toBe("amber");
    expect(personTone(row("A", "A", [], "current", "waived", "not_required"))).toBe("green");
  });

  it("is grey when nothing is asked of them, or all of it is waived", () => {
    expect(personTone(row("A", "A", []))).toBe("grey");
    expect(personTone(row("A", "A", [], "not_required", "waived"))).toBe("grey");
  });
});

describe("the classroom's desks", () => {
  it("has a desk for each role, by name, and someone with two roles sits at both", () => {
    const out = desks(room(row("LL042", "Kim Lee", [PICKER, FORKLIFT], "missing"), row("LL050", "Ana Diaz", [PICKER], "current")));
    expect(out.map((d) => d.name)).toEqual(["Forklift operator", "Picker"]);
    expect(out[0].people.map((p) => p.code)).toEqual(["LL042"]);
    expect(out[1].people.map((p) => p.code)).toEqual(["LL042", "LL050"]);
  });

  it("seats those who need a look first, then goes by name", () => {
    const [picker] = desks(room(
      row("A1", "Abe", [PICKER], "current"), row("B1", "Bo", [PICKER], "expiring"), row("C1", "Cy", [PICKER]),
      row("D1", "Di", [PICKER], "lapsed"), row("E1", "Ed", [PICKER], "missing"),
    ));
    expect(picker.people.map((p) => `${p.name} ${p.tone}`)).toEqual(["Di red", "Ed red", "Bo amber", "Abe green", "Cy grey"]);
    expect(picker.tally).toEqual({ red: 2, amber: 1, green: 1, grey: 1 });
    expect(tallyWords(picker.tally)).toBe("1 current, 1 expiring, 2 need training, 1 nothing due");
  });

  it("sits nobody down who has no role, and counts them apart", () => {
    const m = room(row("LL060", "Zed Ng", []), row("LL042", "Kim Lee", [PICKER], "current"));
    expect(desks(m).map((d) => d.key)).toEqual(["picker"]);
    expect(unseated(m).map((p) => p.code)).toEqual(["LL060"]);
    expect(desks(room())).toEqual([]);
  });

  it("counts everyone once, however many roles they have", () => {
    const m = room(row("LL042", "Kim Lee", [PICKER, FORKLIFT], "missing"), row("LL050", "Ana Diaz", [PICKER], "current"));
    expect(everyone(m)).toEqual({ red: 1, amber: 0, green: 1, grey: 0 });
  });
});

describe("where things go in the room", () => {
  it("projects as Simple WMS does: x down to the right, y down to the left, z up", () => {
    expect(scr(100, 0)).toEqual([86.6, 50]);
    expect(scr(0, 100)).toEqual([-86.6, 50]);
    expect(scr(0, 0, 30)).toEqual([0, -30]);
  });

  it("puts three desks in a row behind the front, then starts another row", () => {
    expect(COLS).toBe(3);
    const spots = [0, 1, 2, 3].map(deskAt);
    expect(spots.slice(0, 3).map((s) => s.y)).toEqual([FRONT, FRONT, FRONT]);
    expect(spots[1].x - spots[0].x).toBe(spots[2].x - spots[1].x);
    expect(spots[3]).toEqual({ x: spots[0].x, y: FRONT + 170 });
  });

  it("seats people in a row behind their desk, facing the board", () => {
    const desk = deskAt(0);
    const seats = [0, 1, 5].map((k) => seatAt(desk, k));
    expect(new Set(seats.map((s) => s.y)).size).toBe(1);
    expect(seats[0].y).toBeGreaterThan(desk.y);
    expect(seats[2].x).toBeLessThan(desk.x + 150);
  });

  it("grows the room by a row for every three desks, and the picture with it", () => {
    expect(roomSize(1)).toEqual(roomSize(3));
    expect(roomSize(4).d - roomSize(3).d).toBe(170);
    expect(roomSize(40).w).toBe(roomSize(1).w);
    expect(viewBox(40).h).toBeGreaterThan(viewBox(3).h);
  });

  it("lays a link over the picture in percent of it", () => {
    const box = viewBox(3);
    const [px, py] = scr(0, 0);
    expect(over(3, 0, 0)).toEqual({
      left: `${Number((((px - box.x) / box.w) * 100).toFixed(2))}%`,
      top: `${Number((((py - box.y) / box.h) * 100).toFixed(2))}%`,
    });
  });
});

describe("Game Mode, for this viewer", () => {
  it("is on unless they turned it off, and remembers it in this browser", () => {
    expect(getGamePrefs()).toEqual({ classroom: true });
    setGamePrefs({ classroom: false });
    expect(window.localStorage.getItem(GAME_PREFS_KEY)).toBe('{"classroom":false}');
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ classroom: false });
  });

  it("starts on when what is kept can't be read", () => {
    window.localStorage.setItem(GAME_PREFS_KEY, "{not json");
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ classroom: true });
    window.localStorage.setItem(GAME_PREFS_KEY, '{"classroom":"no"}');
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ classroom: true });
  });

  it("still switches when the browser keeps nothing", () => {
    const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("private mode"); });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("private mode"); });
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ classroom: true });
    setGamePrefs({ classroom: false });
    expect(getGamePrefs()).toEqual({ classroom: false });
    expect(blocked).toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Test Files  1 failed | 10 passed (11)` and `Tests  60 passed (60)`: `Error: Failed to resolve import "../lib/classroom" from "src/test/classroom.test.ts". Does the file exist?`, so the new file stops while collecting its tests.

**Step 3: Minimal implementation**

`apps/desktop/src/lib/iso.ts`:
```ts
/** Simple WMS's isometric view, the same angles and the same three faces
 * (apps/desktop/scripts/warehouse_layers.py there): x runs down to the
 * right, y down to the left, z straight up. A rect drawn in a face's own
 * flat coordinates and given that face's transform lands in the picture. */
const n = (v: number) => Number(v.toFixed(1));

/** The floor, or a top at height z: a rect at (x, y). */
export const TOP = (z: number) => `matrix(.866 .5 -.866 .5 0 ${n(-z)})`;
/** The face at y = y1, seen from the front left: a rect at (x, -z). */
export const LEFT = (y1: number) => `matrix(.866 .5 0 1 ${n(-0.866 * y1)} ${n(0.5 * y1)})`;
/** The face at x = x1, seen from the front right: a rect at (y, -z). */
export const RIGHT = (x1: number) => `matrix(-.866 .5 0 1 ${n(0.866 * x1)} ${n(0.5 * x1)})`;

/** Where a point of the room lands in the picture. */
export function scr(x: number, y: number, z = 0): [number, number] {
  return [n((x - y) * 0.866), n((x + y) * 0.5 - z)];
}
```

`apps/desktop/src/lib/classroom.ts`:
```ts
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
```

`apps/desktop/src/lib/gamePrefs.ts`:
```ts
import { useSyncExternalStore } from "react";

/** Game Mode, for whoever sits at this screen: kept in this browser, never
 * sent to Simple LMS, so one person's plain desktop is nobody else's
 * business. Off, the desktop is as it was before the classroom: the matrix
 * first, and each screen a page of its own. */
export interface GamePrefs {
  /** the classroom, with every screen opening as a drawer over it */
  classroom: boolean;
}

export const GAME_PREFS_KEY = "lms.game";
export const DEFAULT_PREFS: GamePrefs = { classroom: true };

function read(): GamePrefs {
  try {
    const raw = window.localStorage.getItem(GAME_PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<GamePrefs> | null;
    return { classroom: typeof parsed?.classroom === "boolean" ? parsed.classroom : DEFAULT_PREFS.classroom };
  } catch {
    return DEFAULT_PREFS;
  }
}

let current: GamePrefs | null = null;
const listeners = new Set<() => void>();

export function getGamePrefs(): GamePrefs {
  if (!current) current = read();
  return current;
}

export function setGamePrefs(change: Partial<GamePrefs>): void {
  current = { ...getGamePrefs(), ...change };
  try { window.localStorage.setItem(GAME_PREFS_KEY, JSON.stringify(current)); } catch { /* private mode: for this visit only */ }
  for (const l of listeners) l();
}

/** Forget the copy in memory, so the next read comes from storage (tests). */
export function reloadGamePrefs(): void {
  current = null;
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

export function useGamePrefs(): [GamePrefs, (change: Partial<GamePrefs>) => void] {
  const prefs = useSyncExternalStore(subscribe, getGamePrefs, getGamePrefs);
  return [prefs, setGamePrefs];
}
```

So every test starts from the default whatever the one before it switched, in `apps/desktop/src/test/setup.ts`, replace:
```ts
import "@testing-library/jest-dom/vitest";
```
with:
```ts
import "@testing-library/jest-dom/vitest";
import { reloadGamePrefs } from "../lib/gamePrefs";

// Game Mode is each viewer's own, kept in the browser: every test starts with the default
afterEach(() => {
  window.localStorage.clear();
  reloadGamePrefs();
});
```

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  74 passed (74)`, and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src/lib/iso.ts apps/desktop/src/lib/classroom.ts apps/desktop/src/lib/gamePrefs.ts apps/desktop/src/test/setup.ts apps/desktop/src/test/classroom.test.ts
git commit -m "Work out the classroom from the matrix in Simple WMS's isometric view, and keep each viewer's Game Mode in the browser"
```

---

### Task 2: The classroom, where the desktop opens

**Files:**
- Create: `apps/desktop/src/pages/Classroom.tsx`, `apps/desktop/src/ui/ClassroomArt.tsx`
- Modify: `apps/desktop/src/ui/Layout.tsx` (in full below), `apps/desktop/src/App.tsx`, `apps/desktop/src/pages/Matrix.tsx`, `apps/desktop/src/pages/People.tsx`, `apps/desktop/src/index.css`
- Test: create `apps/desktop/src/test/Classroom.test.tsx`; modify `apps/desktop/src/test/Matrix.test.tsx`, `apps/desktop/src/test/Modules.test.tsx`, `apps/desktop/src/test/Policies.test.tsx`, `apps/desktop/src/test/SignIn.test.tsx`

**Step 1: Write the failing tests**

`apps/desktop/src/test/Classroom.test.tsx`:
```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Matrix, MatrixRow, Person } from "../api/types";
import { GAME_PREFS_KEY } from "../lib/gamePrefs";
import { MEL, json, renderApp, stubApi } from "./harness";

const PICKER = { key: "picker", name: "Picker" };
const FORKLIFT = { key: "forklift-operator", name: "Forklift operator" };
const LICENCE = { key: "forklift-licence", name: "Forklift licence", kind: "ticket" as const };

function person(code: string, name: string, roles: { key: string; name: string }[],
                status: "current" | "missing" | "not_required"): MatrixRow {
  return { code, name, roles, supervisor: null, cells: { "forklift-licence": { status, granted_on: null, expires_on: null } } };
}

const ROOM: Matrix = {
  today: "2026-10-12",
  competencies: [LICENCE],
  people: [
    person("LL050", "Ana Diaz", [PICKER], "current"),
    person("LL042", "Kim Lee", [PICKER, FORKLIFT], "missing"),
    person("LL060", "Zed Ng", [], "not_required"),
  ],
};

const KIM: Person = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: null,
  roles: [PICKER, FORKLIFT], active: true, has_pin: true, pin_locked: false, has_password: false,
};

const SUPERVISOR = { ...MEL, permission: "supervisor" as const, scopes: ["training:read", "matrix:read", "roles:read"] };

/** The matrix answers with `matrix`; the matrix's and People's lists, and Kim, are there to open. */
function stubRoom(matrix: Matrix = ROOM, me = MEL) {
  return stubApi((_m, url) => {
    if (url.startsWith("/v1/matrix")) return json(200, matrix);
    if (url === "/v1/roles") return json(200, { items: [{ ...PICKER, competencies: [], people: 2 }], total: 1 });
    if (url.startsWith("/v1/people?")) return json(200, { items: [KIM], total: 1 });
    if (url === "/v1/people/LL042") return json(200, KIM);
    if (url === "/v1/people/LL042/overrides") return json(200, []);
    return null;
  }, me);
}

const tones = (svg: Element) => [...svg.querySelectorAll("[data-tone]")].map((f) => f.getAttribute("data-tone"));

describe("the classroom", () => {
  it("has a desk for each role, with its people sitting at it, those who need a look first", async () => {
    stubRoom();
    const { container } = renderApp("/");
    expect(await screen.findByRole("heading", { name: "Classroom" })).toBeInTheDocument();
    expect(await screen.findByText("3 people: 1 current, 1 need training, 1 nothing due")).toBeInTheDocument();
    const desks = within(screen.getByRole("list", { name: "Desks" }));
    expect(desks.getAllByRole("link", { name: /Open in the matrix$/ }).map((d) => d.getAttribute("aria-label"))).toEqual([
      "Forklift operator: 1 person, 1 need training. Open in the matrix",
      "Picker: 2 people, 1 current, 1 need training. Open in the matrix",
    ]);
    // drawn back to front: Kim at the forklift desk, then Kim (first: she needs training) and Ana at the picker desk
    expect(tones(container.querySelector(".roompic")!)).toEqual(["red", "red", "green"]);
    // Zed has no role, so no desk: he is counted, and People is a click away
    expect(screen.getByText(/1 person has no role yet, so no desk\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Give them one under People" })).toHaveAttribute("href", "/people");
  });

  it("opens the matrix at a desk's role", async () => {
    const { calls } = stubRoom();
    renderApp("/");
    await userEvent.click(await screen.findByRole("link", { name: /^Picker: / }));
    expect(screen.getByTestId("where")).toHaveTextContent("/matrix");
    expect(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url.startsWith("/v1/matrix")).at(-1)?.url).toBe("/v1/matrix?role=picker");
    expect(screen.getByLabelText("Role")).toHaveValue("picker");
  });

  it("opens a person from where they sit", async () => {
    stubRoom();
    renderApp("/");
    const desk = await screen.findByRole("list", { name: "At the Picker desk" });
    await userEvent.click(within(desk).getByRole("link", { name: "Kim Lee: need training" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/people");
    expect(await screen.findByRole("dialog", { name: "Kim Lee" })).toBeInTheDocument();
  });

  it("seats six at a desk and counts the rest", async () => {
    const crowd = Array.from({ length: 18 }, (_, i) => person(`P${i + 10}`, `Person ${i + 10}`, [PICKER], "current"));
    stubRoom({ ...ROOM, people: crowd });
    const { container } = renderApp("/");
    const desk = await screen.findByRole("link", { name: /^Picker: 18 people/ });
    expect(desk).toHaveTextContent("Picker+12");
    expect(container.querySelectorAll(".roompic [data-tone]")).toHaveLength(6);
    expect(within(screen.getByRole("list", { name: "At the Picker desk" })).getAllByRole("link")).toHaveLength(6);
  });

  it("says when there are no desks yet", async () => {
    stubRoom({ ...ROOM, people: [] });
    renderApp("/");
    expect(await screen.findByText(/No desks yet\. Add roles, then give people roles under People/)).toBeInTheDocument();
  });

  it("shows a supervisor their team's desks, without the people links they can't open", async () => {
    stubRoom(ROOM, SUPERVISOR);
    renderApp("/");
    expect(await screen.findByRole("link", { name: /^Picker: / })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "At the Picker desk" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Give them one under People" })).not.toBeInTheDocument();
  });

  it("tells a supervisor when nobody in their team has a desk", async () => {
    stubRoom({ ...ROOM, people: [] }, SUPERVISOR);
    renderApp("/");
    expect(await screen.findByText("Nobody in your team has a role yet, so no desks.")).toBeInTheDocument();
  });

  it("turns Game Mode off in one click, and then the desktop opens on the matrix", async () => {
    stubRoom();
    const { unmount } = renderApp("/");
    const game = await screen.findByRole("button", { name: "Game Mode" });
    expect(game).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(game);
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/matrix");
    expect(game).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(GAME_PREFS_KEY)).toBe('{"classroom":false}');
    unmount();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Classroom" })).not.toBeInTheDocument();
  });
});
```

The matrix has an address of its own now. In `apps/desktop/src/test/Matrix.test.tsx`, `apps/desktop/src/test/Modules.test.tsx` and `apps/desktop/src/test/Policies.test.tsx`, change every `renderApp("/");` to `renderApp("/matrix");` (eight in the first, one in each of the others):
```
sed -i.bak 's#renderApp("/");#renderApp("/matrix");#' apps/desktop/src/test/Matrix.test.tsx apps/desktop/src/test/Modules.test.tsx apps/desktop/src/test/Policies.test.tsx && rm apps/desktop/src/test/*.bak
```
(`Inbox.test.tsx` keeps its `renderApp("/")`: it looks at the bar, which the classroom has too.)

In `apps/desktop/src/test/SignIn.test.tsx`, replace:
```tsx
  it("signs a manager in and opens the matrix", async () => {
```
with:
```tsx
  it("signs a manager in and opens the classroom", async () => {
```

In `apps/desktop/src/test/SignIn.test.tsx`, replace:
```tsx
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
```
with:
```tsx
    expect(await screen.findByRole("heading", { name: "Classroom" })).toBeInTheDocument();
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  9 failed | 73 passed (82)`: the eight new classroom tests (`Unable to find role="heading" and name "Classroom"`, `Unable to find role="link" and name /^Picker: /`, `Unable to find role="button" and name "Game Mode"` and the like) and the sign-in test, which still lands on the matrix. The matrix's own tests already pass at `/matrix`: an unknown address goes to `/`, which is still the matrix.

**Step 3: Minimal implementation**

`apps/desktop/src/ui/ClassroomArt.tsx`:
```tsx
/** The classroom, drawn in Simple WMS's isometric view: inline SVG, no
 * image files, no game engine. It says nothing the links laid over it
 * don't, so screen readers skip it (aria-hidden) and read those. */
import type { ReactNode } from "react";
import { DESK, SEATS, WALL, deskAt, roomSize, seatAt, viewBox, type Desk } from "../lib/classroom";
import { LEFT, RIGHT, TOP, scr } from "../lib/iso";
import type { Tone } from "../lib/status";

type Faces = [top: string, left: string, right: string];

const WOOD: Faces = ["#ECC994", "#D7A96B", "#BC8D52"];
const BLUE: Faces = ["#5B93D6", "#2F6FB8", "#23558E"];
const FILL: Record<Tone, string> = { green: "#1F8A5B", amber: "#E8A317", red: "#C9343D", grey: "#8A95A5" };

/** A box standing on the floor (or at height z), as Simple WMS draws one. */
function Box({ x, y, w, d, h, z = 0, faces }: { x: number; y: number; w: number; d: number; h: number; z?: number; faces: Faces }) {
  const [top, left, right] = faces;
  return (
    <g>
      <rect x={x} y={-(z + h)} width={w} height={h} fill={left} transform={LEFT(y + d)} />
      <rect x={y} y={-(z + h)} width={d} height={h} fill={right} transform={RIGHT(x + w)} />
      <rect x={x} y={y} width={w} height={d} fill={top} transform={TOP(z + h)} />
    </g>
  );
}

/** The floor, the two back walls, the board and the teacher's desk. */
function Room({ count }: { count: number }) {
  const { w, d } = roomSize(count);
  return (
    <g>
      <rect x={0} y={0} width={w} height={d} rx={12} fill="#EEF2F7" transform={TOP(0)} />
      <rect x={0} y={-WALL} width={w} height={WALL} fill="#DCE5F1" transform={LEFT(0)} />
      <rect x={0} y={-WALL} width={d} height={WALL} fill="#C9D6E8" transform={RIGHT(0)} />
      {/* the board, on the front wall, and its chalk */}
      <rect x={170} y={-100} width={310} height={66} rx={4} fill="#C8A36A" transform={LEFT(0)} />
      <rect x={176} y={-95} width={298} height={56} rx={2} fill="#2E5E4E" transform={LEFT(0)} />
      <rect x={196} y={-80} width={120} height={3} rx={1.5} fill="#E8F0FA" opacity={0.7} transform={LEFT(0)} />
      <rect x={196} y={-68} width={180} height={3} rx={1.5} fill="#E8F0FA" opacity={0.5} transform={LEFT(0)} />
      <Box x={250} y={70} w={150} h={36} d={56} faces={BLUE} />
    </g>
  );
}

/** One person at their desk, seen from behind, facing the board. Someone
 * who needs training has a "!" over their head, so it isn't colour alone. */
function Pupil({ tone, at }: { tone: Tone; at: [number, number] }) {
  const [x, y] = at;
  return (
    <g transform={`translate(${x} ${y})`} data-tone={tone}>
      {/* the hop moves this inner group, so it never undoes the place above */}
      <g className={tone === "red" ? "hop" : undefined}>
        <path d="M-9 0V-14a9 9 0 0 1 18 0V0Z" fill={FILL[tone]} />
        <circle cx="0" cy="-29" r="7" fill={FILL[tone]} />
        {tone === "red" && <text x="0" y="-40" textAnchor="middle" fontSize="13" fontWeight="800" fill="#A3242C">!</text>}
      </g>
    </g>
  );
}

/** The room with a desk for each role and up to six people at each, those
 * who need a look first; drawn back to front, so nearer things cover
 * farther ones. With no desks given it is the empty room. */
export function ClassroomPicture({ desks }: { desks: Desk[] }) {
  const box = viewBox(desks.length);
  const items: [depth: number, node: ReactNode][] = [];
  desks.forEach((desk, i) => {
    const spot = deskAt(i);
    items.push([spot.x + spot.y, <Box key={`desk-${desk.key}`} x={spot.x} y={spot.y} w={DESK.w} d={DESK.d} h={DESK.h} faces={WOOD} />]);
    desk.people.slice(0, SEATS).forEach((p, k) => {
      const seat = seatAt(spot, k);
      items.push([seat.x + seat.y, <Pupil key={`${desk.key}-${p.code}`} tone={p.tone} at={scr(seat.x, seat.y)} />]);
    });
  });
  items.sort((a, b) => a[0] - b[0]);
  return (
    <svg viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`} aria-hidden="true" focusable="false" className="roompic">
      <Room count={desks.length} />
      {items.map(([, node]) => node)}
    </svg>
  );
}
```

`apps/desktop/src/pages/Classroom.tsx`:
```tsx
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Matrix } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DESK, SEATS, TONE_WORDS, deskAt, desks as deskList, everyone, over, seatAt, tallyWords, unseated } from "../lib/classroom";
import type { Tone } from "../lib/status";
import { useLoad } from "../lib/useLoad";
import { ClassroomPicture } from "../ui/ClassroomArt";
import { Problem } from "../ui/Drawer";

const KEY: Tone[] = ["green", "amber", "red", "grey"];

const people = (n: number) => `${n} ${n === 1 ? "person" : "people"}`;

/** Game Mode's home: a classroom in Simple WMS's isometric view, a desk for
 * each role with its people sitting at it, coloured by how current they
 * are. Drawn from the matrix, so it says what the matrix says. Each desk's
 * name opens the matrix at that role; each person opens their page. */
export function Classroom() {
  const { me, can } = useAuth();
  const matrix = useLoad(() => api.get<Matrix>("/v1/matrix"), []);
  const desks = useMemo(() => (matrix.data ? deskList(matrix.data) : null), [matrix.data]);
  const standing = matrix.data ? unseated(matrix.data) : [];
  const all = matrix.data ? everyone(matrix.data) : null;
  const headcount = matrix.data?.people.length ?? 0;
  const seesPeople = can("people:read");

  return (
    <main className="classroom">
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto flex flex-col gap-1">
          <h1>Classroom</h1>
          {all && headcount > 0 && <div className="small">{people(headcount)}: {tallyWords(all)}</div>}
          {standing.length > 0 && (
            <div className="small">
              {standing.length === 1 ? "1 person has" : `${standing.length} people have`} no role yet, so no desk.
              {seesPeople && <> <Link to="/people">Give them one under People</Link>.</>}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Key">
          {KEY.map((t) => <span key={t} className={`pill t-${t}`}><span className={`dot ${t}`} aria-hidden="true" />{TONE_WORDS[t]}</span>)}
        </div>
      </div>
      <Problem error={matrix.error} />
      {!desks && !matrix.error && <div className="small" aria-live="polite">Loading…</div>}
      {desks && desks.length === 0 && (
        <div className="card small">
          {me?.permission === "supervisor"
            ? "Nobody in your team has a role yet, so no desks."
            : "No desks yet. Add roles, then give people roles under People: each role gets a desk."}
        </div>
      )}
      {desks && desks.length > 0 && (
        <div className="room">
          <ClassroomPicture desks={desks} />
          <ul className="desks" aria-label="Desks">
            {desks.map((d, i) => {
              const spot = deskAt(i);
              const words = tallyWords(d.tally);
              const more = d.people.length - SEATS;
              return (
                <li key={d.key}>
                  <Link to={`/matrix?role=${encodeURIComponent(d.key)}`} className="desktag"
                        style={over(desks.length, spot.x + DESK.w / 2, spot.y, 70)}
                        aria-label={`${d.name}: ${people(d.people.length)}, ${words}. Open in the matrix`}>
                    {d.name}{more > 0 && <span className="more">+{more}</span>}
                  </Link>
                  {seesPeople && (
                    <ul aria-label={`At the ${d.name} desk`}>
                      {d.people.slice(0, SEATS).map((p, k) => {
                        const seat = seatAt(spot, k);
                        return (
                          <li key={p.code}>
                            <Link to={`/people?person=${encodeURIComponent(p.code)}`} className="seat"
                                  style={over(desks.length, seat.x, seat.y, 18)}
                                  aria-label={`${p.name}: ${TONE_WORDS[p.tone]}`} title={`${p.name}: ${TONE_WORDS[p.tone]}`} />
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </main>
  );
}
```

`apps/desktop/src/ui/Layout.tsx` (in full):
```tsx
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useGamePrefs } from "../lib/gamePrefs";
import { Classroom } from "../pages/Classroom";
import { Logo } from "./Logo";

/** The bar along the top, then the screen. In Game Mode the desktop opens
 * on the classroom; without it, on the matrix, as it did before. */
export function Layout() {
  const { me, can, signOut } = useAuth();
  const [prefs, setPrefs] = useGamePrefs();
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen">
      <header className="hdr">
        <div className="brand"><Logo />Simple LMS</div>
        <nav className="nav" aria-label="Screens">
          <NavLink to="/matrix">Matrix</NavLink>
          {can("people:read") && <NavLink to="/people">People</NavLink>}
          {can("roles:read") && <NavLink to="/roles">Roles</NavLink>}
          {can("competencies:read") && <NavLink to="/competencies">Competencies</NavLink>}
          {can("tickets:verify") && <NavLink to="/inbox">Inbox</NavLink>}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <button type="button" className="btn" aria-pressed={prefs.classroom} onClick={() => setPrefs({ classroom: !prefs.classroom })}
                  title="The classroom, just for you on this computer">Game Mode</button>
          <span className="small">{me?.name} · {me?.permission}</span>
          <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      {prefs.classroom && pathname === "/" ? <Classroom /> : <Outlet />}
    </div>
  );
}
```

In `apps/desktop/src/App.tsx`, replace:
```tsx
        <Route element={<Layout />}>
          <Route index element={<Matrix />} />
```
with:
```tsx
        <Route element={<Layout />}>
          {/* Game Mode draws the classroom here; without it the desktop opens on the matrix */}
          <Route index element={<Navigate to="/matrix" replace />} />
          <Route path="/matrix" element={<Matrix />} />
```

In `apps/desktop/src/pages/Matrix.tsx`, replace:
```tsx
import { useMemo, useState } from "react";
```
with:
```tsx
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
```

In `apps/desktop/src/pages/Matrix.tsx`, replace:
```tsx
  const { me } = useAuth();
  const [role, setRole] = useState("");
```
with:
```tsx
  const { me } = useAuth();
  // a desk in the classroom opens the matrix at its role
  const [params] = useSearchParams();
  const [role, setRole] = useState(() => params.get("role") ?? "");
```

In `apps/desktop/src/pages/People.tsx`, replace:
```tsx
import { useState, type FormEvent } from "react";
```
with:
```tsx
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
```

In `apps/desktop/src/pages/People.tsx`, replace:
```tsx
  const { can } = useAuth();
  const [q, setQ] = useState("");
```
with:
```tsx
  const { can } = useAuth();
  // a person in the classroom opens People at their drawer
  const [params] = useSearchParams();
  const [q, setQ] = useState("");
```

In `apps/desktop/src/pages/People.tsx`, replace:
```tsx
  const [open, setOpen] = useState<string | "new" | null>(null);
```
with:
```tsx
  const [open, setOpen] = useState<string | "new" | null>(() => params.get("person"));
```

In `apps/desktop/src/index.css`, replace:
```css
  --color-grey-bg: #EEF1F4;
```
with:
```css
  --color-grey-bg: #EEF1F4;
  /* the classroom: a grey for the people nothing is asked of */
  --color-grey: #8A95A5;
```

In `apps/desktop/src/index.css`, replace:
```css
  .dbody { flex: 1; overflow: auto; padding: 0 24px 32px; display: flex; flex-direction: column; gap: 16px; }
}
```
with:
```css
  .dbody { flex: 1; overflow: auto; padding: 0 24px 32px; display: flex; flex-direction: column; gap: 16px; }

  /* Game Mode: its switch, and the classroom */
  .btn[aria-pressed="true"] { background: var(--color-tint); border-color: var(--color-blue); color: var(--color-blue-dark); }
  .classroom { padding: 20px 24px 40px; display: flex; flex-direction: column; gap: 16px; }
  .classroom h1 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: -0.3px; }
  .classroom h1:focus { outline: none; }
  .room { position: relative; width: 100%; max-width: 1100px; margin: 0 auto; }
  .roompic { display: block; width: 100%; height: auto; }
  .desks, .desks ul { list-style: none; margin: 0; padding: 0; }
  .desktag { position: absolute; transform: translate(-50%, -100%); padding: 5px 12px; border-radius: 999px; background: #fff; border: 1px solid var(--color-line-2); box-shadow: var(--shadow-soft); color: var(--color-ink); font-size: 13px; font-weight: 800; white-space: nowrap; text-decoration: none; }
  .desktag:hover { border-color: var(--color-blue); color: var(--color-blue-dark); }
  .desktag .more { margin-left: 6px; color: var(--color-muted); }
  .seat { position: absolute; width: 20px; height: 34px; transform: translate(-50%, -50%); border-radius: 8px; }
  .seat:hover { background: rgba(47, 111, 184, 0.15); }
  .dot { width: 9px; height: 9px; border-radius: 999px; display: inline-block; }
  .dot.green { background: var(--color-green); }
  .dot.amber { background: var(--color-amber); }
  .dot.red { background: var(--color-red); }
  .dot.grey { background: var(--color-grey); }
}

/* Someone who needs training hops now and then, unless the viewer asked
 * their computer for less movement. */
@keyframes lms-hop { 0%, 84%, 100% { transform: translateY(0); } 92% { transform: translateY(-5px); } }
.hop { animation: lms-hop 2.8s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .hop { animation: none; }
}
```

The hop moves an inner group of each figure, never the group that places it: a CSS transform on an SVG element replaces its `transform` attribute, so animating the outer one would throw the figure to the room's corner.

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  82 passed (82)`, and no type errors.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Open the desktop on the classroom, a desk for each role, with Game Mode a switch in the bar and the matrix at /matrix"
```

---

### Task 3: Every screen a drawer over the classroom

**Files:**
- Create: `apps/desktop/src/ui/screens.ts`, `apps/desktop/src/ui/ScreenPanel.tsx`, `apps/desktop/src/ui/focusReturn.ts`
- Modify: `apps/desktop/src/ui/Layout.tsx` (in full below), `apps/desktop/src/ui/ClassroomArt.tsx`, `apps/desktop/src/pages/Classroom.tsx`, `apps/desktop/src/index.css`
- Test: `apps/desktop/src/test/Classroom.test.tsx`

**Step 1: Write the failing tests**

In `apps/desktop/src/test/Classroom.test.tsx`, replace:
```tsx
import { screen, within } from "@testing-library/react";
```
with:
```tsx
import { screen, waitFor, within } from "@testing-library/react";
```

In `apps/desktop/src/test/Classroom.test.tsx`, replace:
```tsx
    expect(screen.queryByRole("heading", { name: "Classroom" })).not.toBeInTheDocument();
  });
});
```
with:
```tsx
    expect(screen.queryByRole("heading", { name: "Classroom" })).not.toBeInTheDocument();
  });
});

describe("screens over the classroom", () => {
  it("opens each screen as a drawer over the classroom, named as the bar names it", async () => {
    stubRoom();
    renderApp("/people");
    const drawer = await screen.findByRole("region", { name: "People" });
    expect(within(drawer).getByRole("heading", { name: "People" })).toBeInTheDocument();
    // keyboard users start in the drawer, at the way back
    const back = screen.getByRole("link", { name: "Back to the classroom" });
    expect(back).toHaveFocus();
    // the bar stays: the matrix is one click away
    expect(within(screen.getByRole("navigation", { name: "Screens" })).getByRole("link", { name: "Matrix" })).toBeInTheDocument();
    await userEvent.click(back);
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
    expect(await screen.findByRole("heading", { name: "Classroom" })).toHaveFocus();
  });

  it("goes back to the classroom on Escape, once a drawer inside it has closed", async () => {
    stubApi((_m, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, ROOM);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, []);
      return null;
    });
    renderApp("/matrix");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" }));
    expect(await screen.findByRole("dialog", { name: "Forklift licence" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/matrix");
    await userEvent.keyboard("{Escape}");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });

  it("gives focus back to the desk that opened the screen", async () => {
    stubRoom();
    renderApp("/");
    await userEvent.click(await screen.findByRole("link", { name: /^Picker: / }));
    await screen.findByRole("region", { name: "Matrix" });
    await userEvent.click(screen.getByRole("link", { name: "Back to the classroom" }));
    await waitFor(() => expect(screen.getByRole("link", { name: /^Picker: / })).toHaveFocus());
  });

  it("keeps each screen a page of its own with Game Mode off", async () => {
    window.localStorage.setItem(GAME_PREFS_KEY, '{"classroom":false}');
    stubRoom();
    renderApp("/people");
    expect(await screen.findByRole("heading", { name: "People" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "People" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Back to the classroom" })).not.toBeInTheDocument();
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/desktop && npm test`
Expected: FAIL: `Tests  3 failed | 83 passed (86)`: `Unable to find role="region" and name "People"` (and `"Matrix"`), and Escape doesn't leave `/matrix`. The fourth already passes: it guards the plain desktop, which this task must not change.

**Step 3: Minimal implementation**

`apps/desktop/src/ui/screens.ts`:
```ts
/** Every screen the desktop has, in the order the bar along the top shows
 * them, with the scope that shows each. In Game Mode each opens as a drawer
 * over the classroom, named from here, so the bar and the drawer never disagree.
 * A screen a later step adds is a line here and its route in App.tsx. */
export interface Screen { to: string; label: string; scope: string }

export const SCREENS: Screen[] = [
  { to: "/matrix", label: "Matrix", scope: "matrix:read" },
  { to: "/people", label: "People", scope: "people:read" },
  { to: "/roles", label: "Roles", scope: "roles:read" },
  { to: "/competencies", label: "Competencies", scope: "competencies:read" },
  { to: "/inbox", label: "Inbox", scope: "tickets:verify" },
];

/** The drawer's name for a path: the screen it is, or under. */
export function screenTitle(pathname: string): string {
  return SCREENS.find((s) => pathname === s.to || pathname.startsWith(`${s.to}/`))?.label ?? "Simple LMS";
}
```

If the bar in `Layout.tsx` on your base has links the list above doesn't (steps 4 to 6 add **Sign off**, **Settings** and the like), add a line to `SCREENS` for each, where it sits in the bar, with the path of its `NavLink` and the scope its `can(...)` checks; a link with no check (as the matrix had) gets the scope its screen's first request needs. Its route in `App.tsx` stays as it is.

`apps/desktop/src/ui/focusReturn.ts`:
```ts
/** Where keyboard focus goes when a screen's drawer closes, as in Simple
 * WMS. The classroom isn't drawn while a drawer is open, so the desk or
 * person that opened it is remembered by its data-return-focus key. */

let opener: string | null = null;
let drawerClosed = false;

export function rememberOpener(key: string | null): void {
  opener = key;
}

export function noteDrawerClosed(): void {
  drawerClosed = true;
}

/** Once, as the classroom comes back: the opener's key, or null for its
 * heading. Undefined when it isn't coming back from a drawer. */
export function takeReturnFocus(): string | null | undefined {
  if (!drawerClosed) return undefined;
  drawerClosed = false;
  const key = opener;
  opener = null;
  return key;
}
```

`apps/desktop/src/ui/ScreenPanel.tsx`:
```tsx
import { useEffect, useRef, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { noteDrawerClosed } from "./focusReturn";
import { screenTitle } from "./screens";

/** Is this Escape someone else's? A drawer open in the screen closes
 * first, and a field being typed in keeps it, so nothing half done is lost. */
export function escapeBelongsElsewhere(target: EventTarget | null): boolean {
  if (document.querySelector('[aria-modal="true"]')) return true;
  return target instanceof HTMLInputElement || target instanceof HTMLSelectElement
    || target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable);
}

/** A screen over the classroom, as every panel is over Simple WMS's map.
 * Escape, the dim or ✕ goes back to the classroom. Not modal: the bar along the top
 * stays one click away, the matrix with it. */
export function ScreenPanel({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const title = screenTitle(pathname);
  const close = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || escapeBelongsElsewhere(e.target)) return;
      navigate("/");
    };
    // on the document, so it hears Escape before a drawer inside (on the window) closes
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);

  // keyboard users start in the drawer; the classroom takes focus back on close
  useEffect(() => {
    close.current?.focus();
    return () => noteDrawerClosed();
  }, []);

  return (
    <>
      <div className="screendim" aria-hidden="true" onClick={() => navigate("/")} />
      <section className="screenpanel" aria-label={title}>
        <div className="screenbar">
          <Link ref={close} to="/" className="btn" aria-label="Back to the classroom" title="Back to the classroom (Esc)">✕</Link>
          <span className="small"><Link to="/">Classroom</Link> / <b>{title}</b></span>
        </div>
        <div className="screenbody">{children}</div>
      </section>
    </>
  );
}
```

`apps/desktop/src/ui/Layout.tsx` (in full):
```tsx
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useGamePrefs } from "../lib/gamePrefs";
import { Classroom } from "../pages/Classroom";
import { rememberOpener } from "./focusReturn";
import { ClassroomBackdrop } from "./ClassroomArt";
import { Logo } from "./Logo";
import { ScreenPanel } from "./ScreenPanel";
import { SCREENS } from "./screens";

/** The bar along the top, then the screen. In Game Mode the desktop opens
 * on the classroom and every screen is a drawer over it; without it, on
 * the matrix, with each screen a page, as it was before. */
export function Layout() {
  const { me, can, signOut } = useAuth();
  const [prefs, setPrefs] = useGamePrefs();
  const { pathname } = useLocation();
  const header = (
    // a screen opened from the bar gives focus back to the classroom's heading
    <header className="hdr" onClickCapture={() => rememberOpener(null)}>
      <div className="brand"><Logo />Simple LMS</div>
      <nav className="nav" aria-label="Screens">
        {SCREENS.filter((s) => can(s.scope)).map((s) => <NavLink key={s.to} to={s.to}>{s.label}</NavLink>)}
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <button type="button" className="btn" aria-pressed={prefs.classroom} onClick={() => setPrefs({ classroom: !prefs.classroom })}
                title="The classroom, just for you on this computer">Game Mode</button>
        <span className="small">{me?.name} · {me?.permission}</span>
        <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>
      </div>
    </header>
  );
  if (!prefs.classroom) {
    return <div className="min-h-screen">{header}<Outlet /></div>;
  }
  return (
    <div className="app">
      {header}
      <div className="stage">
        {pathname === "/" ? <Classroom /> : <><ClassroomBackdrop /><ScreenPanel><Outlet /></ScreenPanel></>}
      </div>
    </div>
  );
}
```

At the end of `apps/desktop/src/ui/ClassroomArt.tsx`, add:
```tsx
const EMPTY: Desk[] = ["a", "b", "c", "d", "e", "f"].map((key) => ({
  key, name: "", people: [], tally: { red: 0, amber: 0, green: 0, grey: 0 },
}));

/** Behind a screen's drawer: the classroom with its desks and nobody at
 * them, so nothing of anyone's shows through. */
export function ClassroomBackdrop() {
  return <div className="backdrop" aria-hidden="true"><ClassroomPicture desks={EMPTY} /></div>;
}
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
import { useMemo } from "react";
```
with:
```tsx
import { useEffect, useMemo, useRef } from "react";
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
import { ClassroomPicture } from "../ui/ClassroomArt";
import { Problem } from "../ui/Drawer";
```
with:
```tsx
import { ClassroomPicture } from "../ui/ClassroomArt";
import { Problem } from "../ui/Drawer";
import { rememberOpener, takeReturnFocus } from "../ui/focusReturn";
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
  const seesPeople = can("people:read");
```
with:
```tsx
  const seesPeople = can("people:read");

  // back from a screen's drawer: focus goes to the desk or person that
  // opened it, once they are drawn, and to the heading meanwhile
  const back = useRef<string | null | undefined>(undefined);
  const root = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const taken = takeReturnFocus();
    if (taken !== undefined) back.current = taken;
  }, []);
  useEffect(() => {
    if (back.current === undefined) return;
    const key = back.current;
    const opener = key ? root.current?.querySelector<HTMLElement>(`[data-return-focus="${CSS.escape(key)}"]`) : null;
    (opener ?? heading.current)?.focus();
    if (opener || !key || desks) back.current = undefined;
  }, [desks]);
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
    <main className="classroom">
```
with:
```tsx
    <main className="classroom" ref={root}
          onClickCapture={(e) => rememberOpener((e.target as HTMLElement).closest<HTMLElement>("[data-return-focus]")?.dataset.returnFocus ?? null)}>
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
<h1>Classroom</h1>
```
with:
```tsx
<h1 ref={heading} tabIndex={-1}>Classroom</h1>
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
<Link to={`/matrix?role=${encodeURIComponent(d.key)}`} className="desktag"
```
with:
```tsx
<Link to={`/matrix?role=${encodeURIComponent(d.key)}`} className="desktag" data-return-focus={`desk-${d.key}`}
```

In `apps/desktop/src/pages/Classroom.tsx`, replace:
```tsx
<Link to={`/people?person=${encodeURIComponent(p.code)}`} className="seat"
                                  style=
```
with:
```tsx
<Link to={`/people?person=${encodeURIComponent(p.code)}`} className="seat"
                                  data-return-focus={`person-${d.key}-${p.code}`} style=
```

In `apps/desktop/src/index.css`, replace:
```css
  .dot.grey { background: var(--color-grey); }
}
```
with:
```css
  .dot.grey { background: var(--color-grey); }
  .app { height: 100vh; display: flex; flex-direction: column; }
  .stage { position: relative; flex: 1; min-height: 0; overflow: hidden; }
  .stage > .classroom { height: 100%; overflow: auto; box-sizing: border-box; }
  .backdrop { position: absolute; inset: 0; padding: 24px; display: flex; justify-content: center; align-items: flex-start; opacity: 0.55; overflow: hidden; }
  .backdrop svg { width: min(1100px, 100%); }
  .screendim { position: absolute; inset: 0; background: rgba(23, 32, 43, 0.3); }
  .screenpanel { position: absolute; top: 0; right: 0; bottom: 0; z-index: 10; width: min(1180px, 100%); display: flex; flex-direction: column; background: var(--color-page); border-radius: 20px 0 0 0; box-shadow: -20px 0 50px rgba(23, 32, 43, 0.2); animation: lms-panel-in 0.2s ease-out; }
  .screenbar { display: flex; align-items: center; gap: 12px; padding: 14px 24px 0; }
  .screenbody { flex: 1; min-height: 0; overflow: auto; }
}
```

In `apps/desktop/src/index.css`, replace:
```css
@media (prefers-reduced-motion: reduce) {
  .hop { animation: none; }
}
```
with:
```css
/* A screen's drawer slides in; it ends with no transform, so a drawer
 * inside it is still placed against the window. */
@keyframes lms-panel-in { from { transform: translateX(32px); opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .hop, .screenpanel { animation: none; }
}
```

The drawer sits in `.stage`, below the bar, and only its own dim covers the classroom, so the bar stays usable; a screen's own `Drawer` (`.dim` and `.drawer`, fixed, inside the panel's `z-index: 10`) still covers everything, the bar included, as a modal should.

**Step 4: Run them to see them pass**

Run: `cd apps/desktop && npm test && npm run typecheck`
Expected: `Tests  86 passed (86)`, and no type errors. Every screen's own tests (People, Roles, Competencies, Inbox, the matrix, and steps 4 to 6's) now run inside the drawer, since Game Mode is on by default: they pass unchanged, which is the proof that the drawer wraps them. If one of steps 4 to 6's screens fails here, it is almost always an Escape it handles itself or a `role="dialog"` it draws without `aria-modal`: make its dialog `aria-modal="true"`, as `Drawer` is, rather than teaching the panel about it.

**Step 5: Commit**

```
git add apps/desktop/src
git commit -m "Open every screen as a drawer over the classroom, named from one list with the bar"
```

---

### Task 4: Ding! out loud on a pass

**Files:**
- Create: `apps/learner/src/lib/game.ts`, `apps/learner/src/lib/sound.ts`
- Modify: `apps/learner/src/pages/ModulePlayer.tsx`, `apps/learner/src/pages/SignPolicy.tsx`, `apps/learner/src/index.css`, `apps/learner/src/test/setup.ts`
- Test: create `apps/learner/src/test/game.test.tsx`; modify `apps/learner/src/test/harness.tsx`, `apps/learner/src/test/policies.test.tsx`

**Step 1: Write the failing tests**

At the end of `apps/learner/src/test/harness.tsx`, after `renderApp`, add:
```tsx
/** An AudioContext that counts the notes it is asked to play. */
export function listen() {
  const heard = { notes: 0, woken: 0 };
  class FakeAudioContext {
    state = "suspended";
    currentTime = 0;
    destination = {};
    resume() { heard.woken += 1; this.state = "running"; return Promise.resolve(); }
    createOscillator() {
      return { type: "", frequency: { setValueAtTime() {} }, connect: (n: unknown) => n, start() { heard.notes += 1; }, stop() {} };
    }
    createGain() {
      return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (n: unknown) => n };
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return heard;
}
```

`apps/learner/src/test/game.test.tsx`:
```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Module } from "../api/types";
import { GAME_PREFS_KEY, getGamePrefs, reloadGamePrefs } from "../lib/game";
import { json, KIM, listen, renderApp, stubApi } from "./harness";

const item = (key: string, name: string, status: string) =>
  ({ key, name, kind: "module", status, granted_on: null, expires_on: null, card_expires: true, waiting: false });
const training = (...items: ReturnType<typeof item>[]) => ({ person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12", items });

const INDUCTION: Module = {
  key: "site-induction", name: "Site induction", resume_at: 1,
  version: {
    id: 1, version: 1, pass_mark: 80,
    pages: [{ kind: "text", title: "Welcome", body: "Sign in at the gatehouse.", url: null, file: null }],
    questions: [{ prompt: "Where do you sign in?", options: ["The gatehouse", "The canteen"] }],
  },
};
const ATTEMPT = { id: 1, version: 1, correct: 1, total: 1, score: 100, pass_mark: 80, passed: true, created_at: "2026-10-12T01:00:00Z" };

/** The site induction's quiz, answered right or wrong. */
async function handIn(passed: boolean) {
  stubApi((method, url) => {
    if (url === "/v1/people/LL042/training") return json(200, training(item("site-induction", "Site induction", "missing")));
    if (url === "/v1/modules/site-induction") return json(200, INDUCTION);
    if (method === "POST" && url === "/v1/modules/site-induction/attempts") {
      return json(201, passed ? ATTEMPT : { ...ATTEMPT, correct: 0, score: 0, passed: false });
    }
    return null;
  });
  renderApp(KIM, Date.now(), "/module/site-induction");
  await userEvent.click(await screen.findByLabelText(passed ? "The gatehouse" : "The canteen"));
  await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
  await screen.findByRole("status", { name: passed ? "Passed" : "Not passed" });
}

describe("game touches in the learner app", () => {
  it("dings out loud on a pass, woken by the tap that handed it in", async () => {
    const heard = listen();
    await handIn(true);
    expect(heard.woken).toBe(1);
    expect(heard.notes).toBe(2);
  });

  it("stays quiet on a fail", async () => {
    const heard = listen();
    await handIn(false);
    expect(heard.notes).toBe(0);
  });

  it("keeps the sound on when what is kept can't be read", () => {
    window.localStorage.setItem(GAME_PREFS_KEY, "{not json");
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ sound: true });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("private mode"); });
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ sound: true });
  });
});
```

In `apps/learner/src/test/policies.test.tsx`, replace:
```tsx
import { json, KIM, renderApp, stubApi } from "./harness";
```
with:
```tsx
import { json, KIM, listen, renderApp, stubApi } from "./harness";
```

In `apps/learner/src/test/policies.test.tsx`, replace:
```tsx
  it("shows the new version when one came out while they read", async () => {
```
with:
```tsx
  it("says Ding! out loud once it is signed, woken by the tap on Sign", async () => {
    const heard = listen();
    stubApi((method, url) => {
      if (url === "/v1/policies/whs-policy") return json(200, WHS);
      if (method === "POST" && url === "/v1/uploads?purpose=signature") return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") return json(201, { kind: "granted" });
      return null;
    });
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kim Lee");
    signWithAFinger();
    await userEvent.click(screen.getByRole("button", { name: "Sign" }));
    await screen.findByRole("status", { name: "Signed" });
    expect(heard).toEqual({ notes: 2, woken: 1 });
  });

  it("shows the new version when one came out while they read", async () => {
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Test Files  2 failed | 6 passed (8)` and `Tests  1 failed | 61 passed (62)`: `Error: Failed to resolve import "../lib/game" from "src/test/game.test.tsx"`, and the signing test's `expected { notes: +0, woken: +0 } to deeply equal { notes: 2, woken: 1 }`.

**Step 3: Minimal implementation**

`apps/learner/src/lib/game.ts`:
```ts
import { useSyncExternalStore } from "react";

/** The learner app's game touches on this device, kept in this browser and
 * never sent to Simple LMS. On a shared tablet they are the tablet's: they
 * name nobody, so signing out leaves them be. */
export interface GamePrefs {
  /** "Ding!" out loud on a pass */
  sound: boolean;
}

export const GAME_PREFS_KEY = "lms.learner.game";
export const DEFAULT_PREFS: GamePrefs = { sound: true };

function read(): GamePrefs {
  try {
    const raw = window.localStorage.getItem(GAME_PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<GamePrefs> | null;
    return { sound: typeof parsed?.sound === "boolean" ? parsed.sound : DEFAULT_PREFS.sound };
  } catch {
    return DEFAULT_PREFS;
  }
}

let current: GamePrefs | null = null;
const listeners = new Set<() => void>();

export function getGamePrefs(): GamePrefs {
  if (!current) current = read();
  return current;
}

export function setGamePrefs(change: Partial<GamePrefs>): void {
  current = { ...getGamePrefs(), ...change };
  try { window.localStorage.setItem(GAME_PREFS_KEY, JSON.stringify(current)); } catch { /* private mode: for this visit only */ }
  for (const l of listeners) l();
}

/** Forget the copy in memory, so the next read comes from storage (tests). */
export function reloadGamePrefs(): void {
  current = null;
  for (const l of listeners) l();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => { listeners.delete(l); };
}

export function useGamePrefs(): [GamePrefs, (change: Partial<GamePrefs>) => void] {
  const prefs = useSyncExternalStore(subscribe, getGamePrefs, getGamePrefs);
  return [prefs, setGamePrefs];
}
```

`apps/learner/src/lib/sound.ts`:
```ts
/** "Ding!" on a pass, made on the spot with WebAudio as Simple WMS's is: no
 * sound file to ship, cache or licence. Quiet: a cue, not an alarm. */
import { useMemo } from "react";
import { useGamePrefs } from "./game";

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (ctx) return ctx;
  const w = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
  const Make = w.AudioContext ?? w.webkitAudioContext;
  if (!Make) return null;
  try { ctx = new Make(); } catch { ctx = null; }
  return ctx;
}

/** A phone only plays sound a tap started: wake it on the tap that may
 * end in a ding (Hand it in, Sign), so it can sound when the answer comes. */
function wake() {
  const c = audio();
  try { if (c?.state === "suspended") void c.resume(); } catch { /* fine without */ }
}

/** A bright two-note ding. */
function ding() {
  const c = audio();
  if (!c) return;
  try {
    const now = c.currentTime;
    for (const [freq, at, length] of [[1318.5, 0, 0.5], [1760, 0.12, 0.7]]) {
      const osc = c.createOscillator();
      const gain = c.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, now + at);
      gain.gain.setValueAtTime(0.0001, now + at);
      gain.gain.exponentialRampToValueAtTime(0.15, now + at + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + at + length);
      osc.connect(gain).connect(c.destination);
      osc.start(now + at);
      osc.stop(now + at + length + 0.05);
    }
  } catch { /* a browser that won't play is fine */ }
}

/** Forget the audio context, so a test's stand-in is used (tests). */
export function forgetSound(): void {
  ctx = null;
}

/** The ding, if this device has sound on: `wake` in the tap, `ding` on the pass. */
export function useDing() {
  const [{ sound }] = useGamePrefs();
  return useMemo(() => ({
    wake: () => { if (sound) wake(); },
    ding: () => { if (sound) ding(); },
  }), [sound]);
}
```

In `apps/learner/src/pages/ModulePlayer.tsx`, replace:
```tsx
import { useSession } from "../auth/Session";
import { Back, plain } from "../ui";
```
with:
```tsx
import { useSession } from "../auth/Session";
import { useDing } from "../lib/sound";
import { Back, plain } from "../ui";
```

In `apps/learner/src/pages/ModulePlayer.tsx`, replace:
```tsx
  const said = useRef<HTMLElement>(null);
  const again = useRef(false);
```
with:
```tsx
  const said = useRef<HTMLElement>(null);
  const again = useRef(false);
  const { wake, ding } = useDing();
```

In `apps/learner/src/pages/ModulePlayer.tsx`, replace:
```tsx
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<Attempt>(`${path}/attempts`, { version, answers }));
```
with:
```tsx
    e.preventDefault();
    wake();
    setBusy(true);
    setError(null);
    try {
      const attempt = await api.post<Attempt>(`${path}/attempts`, { version, answers });
      if (attempt.passed) ding();
      setResult(attempt);
```

In `apps/learner/src/pages/SignPolicy.tsx`, replace:
```tsx
import { toBlob } from "../lib/picture";
```
with:
```tsx
import { toBlob } from "../lib/picture";
import { useDing } from "../lib/sound";
```

In `apps/learner/src/pages/SignPolicy.tsx`, replace:
```tsx
  const canvas = useRef<HTMLCanvasElement>(null);
```
with:
```tsx
  const canvas = useRef<HTMLCanvasElement>(null);
  const { wake, ding } = useDing();
```

In `apps/learner/src/pages/SignPolicy.tsx`, replace:
```tsx
    if (!policy || !canvas.current) return;
    setBusy(true);
```
with:
```tsx
    if (!policy || !canvas.current) return;
    wake();
    setBusy(true);
```

In `apps/learner/src/pages/SignPolicy.tsx`, replace:
```tsx
        version: policy.version.version, signed_name: name.trim(), signature: signature.id,
      });
      setDone(true);
```
with:
```tsx
        version: policy.version.version, signed_name: name.trim(), signature: signature.id,
      });
      ding();
      setDone(true);
```

(`already_signed` still shows the Ding! panel, quietly: it was signed somewhere else, and the ding went off there.)

In `apps/learner/src/index.css`, replace:
```css
  .choice input { width: 22px; height: 22px; flex: none; }
}
```
with:
```css
  .choice input { width: 22px; height: 22px; flex: none; }
}

/* Ding! pops in, unless the viewer asked their phone for less movement. */
@keyframes lms-pop { 0% { transform: scale(0.6); opacity: 0; } 70% { transform: scale(1.12); opacity: 1; } 100% { transform: scale(1); } }
.ding b { display: inline-block; animation: lms-pop 0.45s ease-out; }
@media (prefers-reduced-motion: reduce) {
  .ding b { animation: none; }
}
```

So no test hears another's sound or setting, in `apps/learner/src/test/setup.ts`, replace:
```ts
import "@testing-library/jest-dom/vitest";
```
with:
```ts
import "@testing-library/jest-dom/vitest";
import { reloadGamePrefs } from "../lib/game";
import { forgetSound } from "../lib/sound";
```

In `apps/learner/src/test/setup.ts`, replace:
```ts
afterEach(() => {
  window.localStorage.clear();
```
with:
```ts
afterEach(() => {
  window.localStorage.clear();
  // game touches are this device's own: every test starts with the default, and no sound of its own
  reloadGamePrefs();
  forgetSound();
```

**Step 4: Run them to see them pass**

Run: `cd apps/learner && npm test && npm run typecheck`
Expected: `Tests  65 passed (65)`, and no type errors.

**Step 5: Commit**

```
git add apps/learner/src
git commit -m "Say Ding! out loud on a pass and a signature, unless this device has the sound off"
```

---

### Task 5: The ring on My training, and the sound's switch

**Files:**
- Modify: `apps/learner/src/ui.tsx`, `apps/learner/src/pages/MyTraining.tsx`, `apps/learner/src/index.css`
- Test: `apps/learner/src/test/game.test.tsx`

**Step 1: Write the failing tests**

In `apps/learner/src/test/game.test.tsx`, replace:
```tsx
import { screen } from "@testing-library/react";
```
with:
```tsx
import { screen, within } from "@testing-library/react";
```

In `apps/learner/src/test/game.test.tsx`, replace:
```tsx
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ sound: true });
  });
});
```
with:
```tsx
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ sound: true });
  });

  it("shows how much is done as a ring", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training"
      ? json(200, training(item("a", "Fire safety", "current"), item("b", "Site induction", "missing"),
                           item("c", "Manual handling", "expiring"))) : null);
    renderApp(KIM);
    expect(await screen.findByText("1 of 3 done")).toBeInTheDocument();
    expect(screen.getByText("2 to go")).toBeInTheDocument();
  });

  it("says all done when it is", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(200, training(item("a", "Fire safety", "current"))) : null);
    renderApp(KIM);
    expect(await screen.findByText("1 of 1 done")).toBeInTheDocument();
    expect(screen.getByText("All done. Nice work.")).toBeInTheDocument();
  });

  it("turns the sound off in one tap on My training, for this device", async () => {
    const heard = listen();
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(200, training(item("a", "Fire safety", "current"))) : null);
    const { unmount } = renderApp(KIM);
    const sound = await screen.findByRole("button", { name: "Sound" });
    expect(sound).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(sound);
    expect(sound).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(GAME_PREFS_KEY)).toBe('{"sound":false}');
    unmount();
    await handIn(true);
    expect(within(screen.getByRole("status", { name: "Passed" })).getByText("Ding!")).toBeInTheDocument();
    expect(heard.notes).toBe(0);
    expect(heard.woken).toBe(0);
  });
});
```

**Step 2: Run them to see them fail**

Run: `cd apps/learner && npm test`
Expected: FAIL: `Tests  3 failed | 65 passed (68)`: `Unable to find an element with the text: 1 of 3 done` (and `1 of 1 done`), and `Unable to find role="button" and name "Sound"`.

**Step 3: Minimal implementation**

In `apps/learner/src/ui.tsx`, replace:
```tsx
/** The top of a screen reached from My training, with the way back. */
```
with:
```tsx
const RING_R = 26;
const RING_AROUND = 2 * Math.PI * RING_R;

/** "3 of 5 done", with a ring that fills as it goes, as the scanner shows a
 * day's goal. The words say it all; the ring is only the picture of it. */
export function Ring({ done, of }: { done: number; of: number }) {
  const all = done === of;
  return (
    <div className={`ring${all ? " all" : ""}`}>
      <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <circle className="track" cx="32" cy="32" r={RING_R} />
        <circle className="fill" cx="32" cy="32" r={RING_R} transform="rotate(-90 32 32)"
                strokeDasharray={`${of ? (RING_AROUND * done) / of : 0} ${RING_AROUND}`} />
        {all && <path className="tick" d="M22 33l7 7 13-15" />}
      </svg>
      <div><b>{done} of {of} done</b><span>{all ? "All done. Nice work." : `${of - done} to go`}</span></div>
    </div>
  );
}

/** The top of a screen reached from My training, with the way back. */
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
import { useSession } from "../auth/Session";
import { groupTraining, nextStep, whenLine } from "../lib/training";
import { Logo, plain } from "../ui";
```
with:
```tsx
import { useSession } from "../auth/Session";
import { useGamePrefs } from "../lib/game";
import { groupTraining, nextStep, whenLine } from "../lib/training";
import { Logo, plain, Ring } from "../ui";
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
function Group(
```
with:
```tsx
function SoundIcon({ on }: { on: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 5 }}>
      <path d="M11 5 6 9H3v6h3l5 4Z" />
      {on ? <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /> : <path d="m16 9 5 6M21 9l-5 6" />}
    </svg>
  );
}

function Group(
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
  const { person, signOut } = useSession();
```
with:
```tsx
  const { person, signOut } = useSession();
  const [prefs, setPrefs] = useGamePrefs();
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
      <div className="top"><Logo />{person?.name}
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer" }} onClick={signOut}>Sign out</button>
      </div>
```
with:
```tsx
      <div className="top"><Logo />{person?.name}
        {/* the one game touch with a switch: the ding out loud, on this device */}
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer" }} aria-pressed={prefs.sound}
                onClick={() => setPrefs({ sound: !prefs.sound })}><SoundIcon on={prefs.sound} />Sound</button>
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer", marginLeft: 0 }} onClick={signOut}>Sign out</button>
      </div>
```

In `apps/learner/src/pages/MyTraining.tsx`, replace:
```tsx
      {g && training!.items.length > 0 && (
        <>
          <Group
```
with:
```tsx
      {g && training!.items.length > 0 && (
        <>
          <Ring done={g.done.length} of={training!.items.length} />
          <Group
```

In `apps/learner/src/index.css`, replace:
```css
  --color-green-ink: #146B45;
```
with:
```css
  --color-green: #1F8A5B;
  --color-green-ink: #146B45;
```

In `apps/learner/src/index.css`, replace:
```css
  .chip { margin-left: auto;
```
with:
```css
  .chip[aria-pressed="false"] { background: var(--color-line); color: var(--color-ink-2); }
  .chip { margin-left: auto;
```

In `apps/learner/src/index.css`, replace:
```css
  .choice input { width: 22px; height: 22px; flex: none; }
}
```
with:
```css
  .choice input { width: 22px; height: 22px; flex: none; }
  .ring { display: flex; align-items: center; gap: 14px; background: #fff; border: 1px solid var(--color-line); border-radius: 16px; padding: 12px 16px; }
  .ring svg { flex: none; }
  .ring .track { fill: none; stroke: var(--color-line); stroke-width: 8; }
  .ring .fill { fill: none; stroke: var(--color-blue); stroke-width: 8; stroke-linecap: round; transition: stroke-dasharray 0.6s ease-out; }
  .ring.all .fill { stroke: var(--color-green); }
  .ring .tick { fill: none; stroke: var(--color-green); stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }
  .ring div { display: flex; flex-direction: column; gap: 2px; }
  .ring b { font-size: 18px; font-weight: 800; }
  .ring span { font-size: 14px; color: var(--color-ink-2); }
}
```

In `apps/learner/src/index.css`, replace:
```css
  .ding b { animation: none; }
}
```
with:
```css
  .ding b { animation: none; }
  .ring .fill { transition: none; }
}
```

The colours go on the ring by class, not as SVG attributes: a CSS variable only works in CSS.

**Step 4: Run them to see them pass**

Run: `cd apps/learner && npm test && npm run typecheck`
Expected: `Tests  68 passed (68)`, and no type errors.

**Step 5: Commit**

```
git add apps/learner/src
git commit -m "Show how much is done as a ring on My training, with a switch for the ding beside Sign out"
```

---

### Task 6: The README and CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Step 1: Write it**

In `README.md`, the status paragraph says which step is done; by now it is step 6. Make its first sentence `Status: **build step 7, Game Mode, is done.**`, keep the list of what is there, add the sentence below after it, and drop "come with the next steps" and what follows (nothing in the design's build order is left):
````markdown
The desktop opens on a classroom, a desk for each role with its people
sitting at it in green, amber or red, and every screen in a drawer over it;
the learner app shows a ring for how much is done and says Ding! out loud.
````

In `README.md`, replace:
````markdown
self-signed): sign in with that email and password and it opens on the
matrix. Add competencies, then roles and what each requires, then people.
Click a cell to see that person's history for it and record a completion.
````
with:
````markdown
self-signed): sign in with that email and password and it opens on the
classroom. Add competencies, then roles and what each requires, then
people. Open **Matrix** in the bar along the top and click a cell to see that
person's history for it and record a completion.

**Game Mode.** The classroom is drawn in the same isometric view as Simple
WMS and Simple TMS: the board and the teacher's desk at the front, then a
desk for each role, three to a row, with the people who have that role
sitting at it (someone with two roles sits at both), coloured by how current
they are: red, with a "!", if anything asked of them has lapsed or is
missing; amber if something runs out within 30 days; green if the rest is
current; grey if nothing is asked. A desk seats six, those who need a look
first, and its label counts the rest ("Picker +12"). Click a desk's label to
open the matrix at that role, or a person to open them in People; someone
with no role yet has no desk, and the line under the heading counts them.
Every screen opens as a drawer over the classroom: ✕, Escape or a click on
the classroom goes back, and the bar along the top stays, so the matrix is
always one click away. **Game Mode** in the bar turns it all off for you, on
that computer: the desktop then opens on the matrix, each screen a page of
its own. It is kept in your browser, never in Simple LMS.
````

In `README.md`, replace:
````markdown
Due soon and Done. A PIN session ends after 15 minutes without a tap, and the
````
with:
````markdown
Due soon and Done, with a ring for how much is done ("3 of 5 done"). A pass
on a module or a signed policy says Ding!, out loud unless **Sound** beside
Sign out is off; that switch is the device's, so on a shared tablet it stays
as the last person left it. A PIN session ends after 15 minutes without a tap, and the
````

In `CLAUDE.md`, replace:
````markdown
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
````
with:
````markdown
- Game Mode: the desktop opens on the classroom (`lib/classroom.ts` works
  it out from `GET /v1/matrix`, in Simple WMS's isometric view from
  `lib/iso.ts`; nothing in the API is for it) and every other route opens in
  `ScreenPanel` over it. A new desktop screen is a line in
  `apps/desktop/src/ui/screens.ts` and a route in `App.tsx`; its own dialogs
  are `aria-modal="true"`, so Escape closes them before the panel. Game
  touches are per viewer, kept in the browser (`lms.game`,
  `lms.learner.game`) and never sent to the API, and everything the
  classroom offers stays reachable with Game Mode off.
- Sister apps: nothing in Simple WMS or Simple TMS changes for Simple LMS. It
````

(If step 3's Task 14 already put a `Files:` bullet before that line, the new bullet goes between them all the same.)

**Step 2: Commit**

```
git add README.md CLAUDE.md
git commit -m "Describe Game Mode's classroom in the README, and its rules in CLAUDE.md"
```

---

### Task 7: Every suite, the builds, and a clean Compose start

**Step 1: Every suite and both builds**

```
(cd api && .venv/bin/pytest -q)
(cd apps/desktop && npm test && npm run typecheck && npm run build)
(cd apps/learner && npm test && npm run typecheck && npm run build)
git diff --stat main -- api docs/api.md
```
Expected: the API suite passes as it did on `main` (this step touches nothing in it); `Tests  86 passed (86)` (plus D) and a build; `Tests  68 passed (68)` (plus L) and a build; and the last command prints nothing: no API file and no `docs/api.md` changed.

**Step 2: Compose from nothing**

This drops the local database and its uploads: only on a machine with nothing to keep.
```
docker compose down -v
docker compose up -d --build
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8033/v1/health && break; sleep 2; done; echo
docker compose ps --format '{{.Service}} {{.State}}'
curl -kfsS "https://localhost:${LMS_HTTPS_PORT:-443}/" | grep -o '<title>[^<]*</title>'
curl -kfsS "https://localhost:${LMS_HTTPS_PORT:-443}/learn/" | grep -o '<title>[^<]*</title>'
```
Expected: `{"status":"ok"}`; `api running`, `caddy running`, `db running`, `worker running`; and both apps' titles through Caddy. Fix anything that is not, then commit the fix with a message that says what it fixes.

---

### Task 8: Manual walkthrough: the classroom, a drawer, a ding

With the stack from Task 7 (and `LMS_HTTPS_PORT=8643` in `.env` beside a sibling), the first admin made with `docker compose exec api lms create-user --code AD001 --name "…" --email …`, and on a phone the learner app at `https://<this machine's address>:8643/learn/` (accept the self-signed certificate). Have the site induction from step 3's walkthrough (a module with a quiz), or make a short one.

**Step 1: The classroom.** Sign in to the desktop as the admin: it opens on **Classroom**, with "No desks yet…". Add competencies **Site induction** (module, refresher 24 months) and **Forklift licence** (ticket), roles **Picker** (requires Site induction) and **Forklift operator** (requires both), and people: Kim (`LL042`, PIN `2468`, both roles), Ana (Picker) and Zed (no role). Close each drawer (✕, or Escape with nothing open in it): the classroom shows the board and the teacher's desk at the front and two desks in the first row, **Forklift operator** and **Picker**, Kim sitting at both, red with a "!", Ana red at Picker. Zed sits nowhere: "1 person has no role yet, so no desk. Give them one under People". Put it beside Simple WMS's map: the same angle, the same light boxes.

**Step 2: Drawers over the classroom.** Click the **Picker** label: the matrix opens as a drawer over the faded, empty classroom with **Role** set to Picker, and only Kim and Ana in it. Click Kim's Site induction cell: its history opens over the matrix, over the bar too. Press Escape: the history closes and the matrix stays. Press Escape again: back to the classroom, with focus on the Picker label. Click Kim where she sits at the Forklift operator desk: People opens with Kim's drawer open; ✕ on her drawer, then Escape: back, with focus on her seat. Open **People** from the bar, then **Roles** from the bar while it is open: the drawer's name follows ("Classroom / Roles"). Click the faded classroom to the left of the drawer: back again. Every screen your base has (Sign off, Settings, webhooks and API keys from steps 4 to 6) opens the same way, named as the bar names it.

**Step 3: Many roles and many people.** Add five more roles and give them to people: the room grows a second row of desks, then a third, and scrolls; it keeps its width. Give Picker to fifteen more people: the Picker desk seats six, red first, and its label says "Picker +12"; its link's name and the matrix still count all eighteen. Make the window narrow (about 960 wide): the picture scales down and every label stays on its desk.

**Step 4: Ding.** On the phone, sign in as Kim: My training shows the ring at "0 of 2 done · 2 to go", with the big buttons as before. Start the Site induction, go through its pages, answer the quiz right and **Hand it in**: the phone dings (two bright notes) and Ding! pops in. Back on My training: "1 of 2 done". Back on the desktop (open and close any drawer, or reload): at the Picker desk Kim is green; at Forklift operator she is still red for her licence.

**Step 5: Game touches off, one click each.** On the phone, tap **Sound** (it greys out): take the module again and pass: Ding! shows, silently. Sign out and in as Ana on the same phone: **Sound** is still off (it is the device's). On the desktop, press **Game Mode** in the bar: the desktop opens on the matrix, each screen a page under the bar, no classroom; reload, and it stays off; another browser on the same computer still opens on the classroom. Press it again to turn it back on.

**Step 6: Less movement, and a screen reader.** Turn on *Reduce motion* (macOS: System Settings → Accessibility → Display; iOS: Settings → Accessibility → Motion) and reload: red figures no longer hop, the drawer appears without sliding, the ring fills without easing, and Ding! appears without popping. With VoiceOver (Cmd+F5), go through the classroom: the picture is skipped; the "Desks" list reads each desk as "Picker: 3 people, 1 current, 2 need training. Open in the matrix", then "At the Picker desk" reads each person and their colour; the key reads its four words.

**Step 7: Nothing on the server.** In the browser's devtools, *Application → Local storage* holds `lms.game` = `{"classroom":true}` on the desktop and `lms.learner.game` = `{"sound":false}` in the learner app, with no name in either; `docker compose logs api | grep -c game` finds nothing, as no request carries them.
