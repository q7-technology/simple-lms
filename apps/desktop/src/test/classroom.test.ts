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
