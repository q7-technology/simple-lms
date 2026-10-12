import type { TrainingItem } from "../api/types";
import { groupTraining, whenLine } from "../lib/training";

const item = (name: string, status: TrainingItem["status"], expires_on: string | null = null): TrainingItem =>
  ({ key: name.toLowerCase().replace(/ /g, "-"), name, kind: "ticket", status, granted_on: null, expires_on });

describe("My training", () => {
  it("puts lapsed and missing in Overdue, expiring in Due soon and current in Done", () => {
    const g = groupTraining([
      item("WHS policy", "missing"),
      item("First aid", "lapsed", "2026-09-30"),
      item("Site induction", "expiring", "2026-11-01"),
      item("Forklift licence", "current", "2031-03-01"),
      item("Fire warden", "lapsed", "2026-01-15"),
      item("Manual handling", "expiring", "2026-10-20"),
      item("Chemical handling", "missing"),
      item("Code of conduct", "current"),
    ]);
    expect(g.overdue.map((i) => i.name)).toEqual(["Fire warden", "First aid", "Chemical handling", "WHS policy"]);
    expect(g.dueSoon.map((i) => i.name)).toEqual(["Manual handling", "Site induction"]);
    expect(g.done.map((i) => i.name)).toEqual(["Code of conduct", "Forklift licence"]);
  });

  it("is empty in every part when there is nothing to do", () => {
    expect(groupTraining([])).toEqual({ overdue: [], dueSoon: [], done: [] });
  });

  it("says when, the Australian way", () => {
    expect(whenLine(item("A", "lapsed", "2026-09-30"))).toBe("Ran out after 30 Sep 2026");
    expect(whenLine(item("A", "missing"))).toBe("Not done yet");
    expect(whenLine(item("A", "expiring", "2026-11-01"))).toBe("Due by 1 Nov 2026");
    expect(whenLine(item("A", "current", "2031-03-01"))).toBe("Done · good until 1 Mar 2031");
    expect(whenLine(item("A", "current"))).toBe("Done · doesn't run out");
  });
});
