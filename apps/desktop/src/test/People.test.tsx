import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Person } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const SAM: Person = {
  id: 3, code: "SV001", name: "Sam Vu", email: "sam@example.com.au", permission: "supervisor", supervisor: null,
  roles: [], active: true, has_pin: true, pin_locked: false, has_password: true,
};
const KIM: Person = {
  ...SAM, id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner",
  supervisor: { code: "SV001", name: "Sam Vu" }, roles: [{ key: "picker", name: "Picker" }], has_password: false,
};
const PICKER = { id: 1, key: "picker", name: "Picker", competencies: [], people: 0 };

describe("people", () => {
  it("adds a learner with a PIN, a supervisor and a role", async () => {
    let people = [SAM];
    const { calls } = stubApi((method, url) => {
      if (method === "GET" && url.startsWith("/v1/people?")) return json(200, { items: people, total: people.length });
      if (url === "/v1/roles") return json(200, { items: [PICKER], total: 1 });
      if (method === "POST" && url === "/v1/people") { people = [KIM, SAM]; return json(201, KIM); }
      if (url === "/v1/people/LL042") return json(200, KIM);
      if (url === "/v1/people/LL042/overrides") return json(200, []);
      if (url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Add person" }));
    const drawer = await screen.findByRole("dialog", { name: "Add person" });
    await userEvent.type(within(drawer).getByLabelText("Code"), "LL042");
    await userEvent.type(within(drawer).getByLabelText("Name"), "Kim Lee");
    await userEvent.selectOptions(within(drawer).getByLabelText("Supervisor"), "SV001");
    await userEvent.type(within(drawer).getByLabelText("PIN (4 to 8 digits)"), "2468");
    await userEvent.click(await within(drawer).findByLabelText("Picker"));
    await userEvent.click(within(drawer).getByRole("button", { name: "Add person" }));

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: "SV001",
      roles: ["picker"], pin: "2468", password: null,
    });
    // the new person opens, ready for extras, waivers and the rest
    expect(await screen.findByRole("dialog", { name: "Kim Lee" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Kim Lee/ })).toBeInTheDocument();
  });

  it("offers a manager learner and supervisor only", async () => {
    stubApi((_method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [SAM], total: 1 });
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Add person" }));
    const options = within(await screen.findByLabelText("Permission")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["learner", "supervisor"]);
  });
});
