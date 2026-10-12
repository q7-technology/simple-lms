import { LOOK, STATUSES, describe as say, formatDate } from "../lib/status";

describe("status colours", () => {
  it("is green, amber, red or grey, as the matrix draws it", () => {
    expect(Object.fromEntries(STATUSES.map((s) => [s, LOOK[s].tone]))).toEqual({
      current: "green", expiring: "amber", lapsed: "red", missing: "red",
      waived: "grey", not_required: "grey",
    });
  });

  it("writes dates the Australian way", () => {
    expect(formatDate("2026-11-01")).toBe("1 Nov 2026");
    expect(formatDate(null)).toBe("");
  });

  it("says what a cell means", () => {
    expect(say({ status: "current", granted_on: "2025-06-01", expires_on: "2027-06-01" })).toBe("Current until 1 Jun 2027");
    expect(say({ status: "current", granted_on: "2025-06-01", expires_on: null })).toBe("Current, doesn't run out");
    expect(say({ status: "expiring", granted_on: "2025-01-01", expires_on: "2026-11-01" })).toBe("Expiring: good until 1 Nov 2026");
    expect(say({ status: "lapsed", granted_on: "2024-01-01", expires_on: "2026-01-01" })).toBe("Lapsed: was good until 1 Jan 2026");
    expect(say({ status: "not_required", granted_on: null, expires_on: null })).toBe("Not required");
  });
});
