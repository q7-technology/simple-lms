import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Matrix } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const MATRIX: Matrix = {
  today: "2026-10-12",
  competencies: [
    { key: "forklift-licence", name: "Forklift licence", kind: "ticket" },
    { key: "site-induction", name: "Site induction", kind: "module" },
  ],
  people: [{
    code: "LL042", name: "Kim Lee", roles: [{ key: "forklift-operator", name: "Forklift operator" }],
    supervisor: { code: "SV001", name: "Sam Vu" },
    cells: {
      "forklift-licence": { status: "missing", granted_on: null, expires_on: null },
      "site-induction": { status: "expiring", granted_on: "2024-10-20", expires_on: "2026-10-20" },
    },
  }],
};

const GRANTED: Matrix = {
  ...MATRIX,
  people: [{ ...MATRIX.people[0], cells: { ...MATRIX.people[0].cells,
    "forklift-licence": { status: "current", granted_on: "2026-10-12", expires_on: "2031-03-01" } } }],
};

describe("the matrix", () => {
  it("colours each cell by its status and says what it means", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/matrix");
    const missing = await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" });
    expect(missing).toHaveClass("t-red");
    const expiring = screen.getByRole("button", { name: "Kim Lee, Site induction: Expiring: good until 20 Oct 2026" });
    expect(expiring).toHaveClass("t-amber");
  });

  it("asks again with the filters", async () => {
    const { calls } = stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [{ key: "picker", name: "Picker", competencies: [], people: 0 }], total: 1 });
      return null;
    });
    renderApp("/matrix");
    await screen.findByRole("button", { name: /Kim Lee, Forklift licence/ });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "lapsed");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "picker");
    await waitFor(() => expect(calls.at(-1)?.url).toBe("/v1/matrix?role=picker&status=lapsed"));
  });

  it("opens a cell's history and records a completion, and the cell goes green", async () => {
    let matrix = MATRIX;
    const records: unknown[] = [];
    const { calls } = stubApi((method, url, body) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (method === "GET" && url.startsWith("/v1/people/LL042/records")) return json(200, records);
      if (method === "POST" && url === "/v1/people/LL042/records") {
        matrix = GRANTED;
        records.unshift({ id: 1, competency: MATRIX.competencies[0], kind: "granted", granted_on: "2026-10-12",
                          expires_on: "2031-03-01", note: (body as { note: string }).note,
                          recorded_by: { code: "MG001", name: "Mel Grant" }, created_at: "2026-10-12T01:00:00Z" });
        return json(201, records[0]);
      }
      return null;
    });
    renderApp("/matrix");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence" });
    expect(await within(drawer).findByText("Nothing recorded yet.")).toBeInTheDocument();
    await userEvent.type(within(drawer).getByLabelText("Good until (optional)"), "2031-03-01");
    await userEvent.type(within(drawer).getByLabelText("Note (optional)"), "LF 0012345, sighted");
    await userEvent.click(within(drawer).getByRole("button", { name: "Record completion" }));

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      competency: "forklift-licence", granted_on: "2026-10-12", expires_on: "2031-03-01", note: "LF 0012345, sighted" });
    expect(await within(drawer).findByText("LF 0012345, sighted")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Current until 1 Mar 2031" })).toHaveClass("t-green");
    // now there is a grant, it can be revoked
    expect(within(drawer).getByRole("button", { name: "Revoke" })).toBeDisabled();
  });

  it("tells a manager they can't record their own", async () => {
    const own = { ...MATRIX, people: [{ ...MATRIX.people[0], code: "MG001", name: "Mel Grant" }] };
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, own);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/MG001/records")) return json(200, []);
      return null;
    });
    renderApp("/matrix");
    await userEvent.click(await screen.findByRole("button", { name: "Mel Grant, Forklift licence: Missing" }));
    expect(await screen.findByText("Nobody records their own competency: ask another manager.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record completion" })).not.toBeInTheDocument();
  });

  it("names each row by its person", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/matrix");
    expect(await screen.findByRole("rowheader", { name: /Kim Lee/ })).toBeInTheDocument();
  });

  it("keeps the drawer open when a filter hides the person after a change", async () => {
    let matrix = MATRIX;
    stubApi((method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (method === "GET" && url.startsWith("/v1/people/LL042/records")) return json(200, []);
      if (method === "POST" && url === "/v1/people/LL042/records") {
        matrix = { ...MATRIX, people: [] }; // no longer missing anything, so the filter drops them
        return json(201, {});
      }
      return null;
    });
    renderApp("/matrix");
    await screen.findByRole("button", { name: /Kim Lee, Forklift licence/ });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "missing");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence" });
    await userEvent.click(within(drawer).getByRole("button", { name: "Record completion" }));
    expect(await screen.findByText("Nobody matches. Try fewer filters.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Forklift licence" })).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says so when the CSV can't be made", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix.csv")) return json(500, { detail: "The export failed. Try again." });
      if (url.startsWith("/v1/matrix")) return json(200, MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/matrix");
    await screen.findByRole("button", { name: /Kim Lee, Forklift licence/ });
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The export failed. Try again.");
  });

  it("keeps every supervisor on offer after choosing one", async () => {
    const person = { email: null, roles: [], active: true, has_pin: false, pin_locked: false, has_password: true, supervisor: null };
    const people = [
      { ...person, id: 3, code: "SV001", name: "Sam Vu", permission: "supervisor" },
      { ...person, id: 5, code: "SV002", name: "Ari Bell", permission: "supervisor" },
      { ...person, id: 4, code: "LL042", name: "Kim Lee", permission: "learner" },
    ];
    stubApi((_method, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, url.includes("supervisor=SV002") ? { ...MATRIX, people: [] } : MATRIX);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people?")) return json(200, { items: people, total: people.length });
      return null;
    });
    renderApp("/matrix");
    const select = await screen.findByLabelText("Supervisor");
    await within(select).findByRole("option", { name: "Ari Bell" });
    await userEvent.selectOptions(select, "SV002");
    expect(await screen.findByText("Nobody matches. Try fewer filters.")).toBeInTheDocument();
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Anyone", "Ari Bell", "Sam Vu"]);
  });
});
