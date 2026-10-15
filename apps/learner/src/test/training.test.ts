import type { TrainingItem } from "../api/types";
import { groupTraining, nextStep, whenLine } from "../lib/training";

const item = (name: string, status: TrainingItem["status"], expires_on: string | null = null): TrainingItem =>
  ({ key: name.toLowerCase().replace(/ /g, "-"), name, kind: "ticket", status, granted_on: null, expires_on,
     card_expires: true, waiting: false });

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

  it("offers the next step: sign a policy, add a ticket, or wait for the check", () => {
    const policy = { ...item("WHS policy", "missing"), kind: "policy" as const };
    expect(nextStep(policy)).toEqual({ to: "/sign/whs-policy", label: "Read and sign" });
    expect(nextStep({ ...policy, status: "current" })).toBeNull();
    expect(nextStep(item("First aid", "lapsed"))).toEqual({ to: "/ticket/first-aid", label: "Add your ticket" });
    expect(nextStep(item("Forklift licence", "expiring"))).toEqual({ to: "/ticket/forklift-licence", label: "Add your ticket" });
    expect(nextStep({ ...item("Forklift licence", "missing"), waiting: true })).toEqual({ waiting: "Sent in · waiting for a manager's check" });
    expect(nextStep(item("Forklift licence", "current"))).toBeNull();
    expect(nextStep({ ...item("Site induction", "current"), kind: "module" })).toBeNull();
  });

  it("offers a module that isn't current", () => {
    const module = { ...item("Site induction", "missing"), kind: "module" as const };
    expect(nextStep(module)).toEqual({ to: "/module/site-induction", label: "Start the module" });
    expect(nextStep({ ...module, status: "expiring" })).toEqual({ to: "/module/site-induction", label: "Start the module" });
    expect(nextStep({ ...module, status: "lapsed" })).toEqual({ to: "/module/site-induction", label: "Start the module" });
  });

  it("says a practical is signed off with their supervisor", () => {
    const practical = { ...item("Forklift practical", "missing"), kind: "practical" as const };
    expect(nextStep(practical)).toEqual({ waiting: "Your supervisor signs this off with you" });
    expect(nextStep({ ...practical, status: "expiring" })).toEqual({ waiting: "Your supervisor signs this off with you" });
    expect(nextStep({ ...practical, status: "current" })).toBeNull();
  });
});
