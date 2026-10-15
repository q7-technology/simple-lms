import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { CompetencyRecord, Matrix, Person } from "../api/types";
import { MEL, json, renderApp, stubApi } from "./harness";

const FORKLIFT = { key: "forklift-licence", name: "Forklift licence", kind: "ticket" as const };
const MATRIX: Matrix = {
  today: "2026-10-12",
  competencies: [FORKLIFT],
  people: [{ code: "LL042", name: "Kim Lee", roles: [], supervisor: null,
             cells: { "forklift-licence": { status: "current", granted_on: "2026-03-01", expires_on: "2031-03-01" } } }],
};
const record = (id: number, granted_on: string): CompetencyRecord => ({
  id, competency: FORKLIFT, kind: "granted", granted_on, expires_on: "2031-03-01", note: null,
  recorded_by: { code: "MG001", name: "Mel Grant" }, policy_version: null, signed_name: null, signature: null,
  ticket: null, quiz: null, signoff: null, created_at: `${granted_on}T01:00:00Z`,
});
const KIM: Person = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: null, roles: [],
  active: true, has_pin: true, pin_locked: false, has_password: false, entra_linked: false,
};

function history(more: (method: string, url: string) => Response | null) {
  return stubApi((method, url) => {
    if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
    if (url === "/v1/roles") return json(200, { items: [], total: 0 });
    if (method === "GET" && url.startsWith("/v1/people/LL042/records")) {
      return json(200, [record(12, "2026-03-01"), record(5, "2021-03-01")]);
    }
    return more(method, url);
  });
}

async function openKimsForklift() {
  renderApp("/matrix");
  await userEvent.click(await screen.findByRole("button", { name: /Kim Lee, Forklift licence/ }));
  return screen.findByRole("dialog", { name: "Forklift licence" });
}

describe("printing", () => {
  it("prints a certificate for the completion that counts", async () => {
    const { calls } = history((method, url) => method === "POST" && url === "/v1/people/LL042/records/12/certificate"
      ? json(202, { job_id: "j-1", template: "lms-certificate", printer: "office" }) : null);
    const drawer = await openKimsForklift();
    const print = await within(drawer).findAllByRole("button", { name: "Print certificate" });
    expect(print).toHaveLength(1);
    await userEvent.click(print[0]);
    expect(await within(drawer).findByText("Sent to Platen, for the printer office.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/v1/people/LL042/records/12/certificate"]);
  });

  it("says so when printing isn't set up", async () => {
    history((method) => method === "POST"
      ? json(409, { detail: "Printing is not set up: give Platen's address in Settings, under Printing.", code: "printing_not_set_up" })
      : null);
    const drawer = await openKimsForklift();
    await userEvent.click(await within(drawer).findByRole("button", { name: "Print certificate" }));
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("Printing is not set up");
  });

  it("isn't offered to a supervisor", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, [record(12, "2026-03-01")]);
      return null;
    }, { ...MEL, permission: "supervisor", scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read"] });
    const drawer = await openKimsForklift();
    expect(await within(drawer).findByText("Counts now")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Print certificate" })).not.toBeInTheDocument();
  });

  it("prints a person's skills card", async () => {
    const { calls } = stubApi((method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [KIM], total: 1 });
      if (url === "/v1/people/LL042") return json(200, KIM);
      if (url === "/v1/people/LL042/overrides") return json(200, []);
      if (url === "/v1/roles" || url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      if (method === "POST" && url === "/v1/people/LL042/skills-card") {
        return json(202, { job_id: "j-2", template: "lms-skills-card", printer: "card printer" });
      }
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee" }));
    const drawer = await screen.findByRole("dialog", { name: "Kim Lee" });
    await userEvent.click(await within(drawer).findByRole("button", { name: "Print skills card" }));
    expect(await within(drawer).findByText("Sent to Platen, for the printer card printer.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/people/LL042/skills-card")).toBe(true);
  });
});
