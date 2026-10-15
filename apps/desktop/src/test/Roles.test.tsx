import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Competency, Role } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const INDUCTION: Competency = { id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: 24, card_expires: null, active: true };
// required by the role, then deactivated: the active list no longer has it
const PICKER: Role = {
  id: 1, key: "picker", name: "Picker", people: 3,
  competencies: [
    { key: "site-induction", name: "Site induction", kind: "module" },
    { key: "old-induction", name: "Old induction", kind: "module" },
  ],
};

describe("roles", () => {
  it("shows a deactivated competency the role still requires, so it can be unticked", async () => {
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/roles") return json(200, { items: [PICKER], total: 1 });
      if (url.startsWith("/v1/competencies")) return json(200, { items: [INDUCTION], total: 1 });
      if (method === "PUT") return json(200, PICKER);
      return null;
    });
    renderApp("/roles");
    await userEvent.click(await screen.findByRole("button", { name: /^Picker/ }));
    const drawer = await screen.findByRole("dialog", { name: "Picker" });
    const old = await within(drawer).findByRole("checkbox", { name: /Old induction \(deactivated\)/ });
    expect(old).toBeChecked();
    expect(within(drawer).getByRole("checkbox", { name: /Site induction/ })).toBeChecked();
    await userEvent.click(old);
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      competencies: ["site-induction"] }));
  });
});
