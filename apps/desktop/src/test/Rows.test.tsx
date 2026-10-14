import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Competency, Person, Role } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const PICKER: Role = { id: 1, key: "picker", name: "Picker", competencies: [], people: 0 };
const INDUCTION: Competency = { id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: 24, card_expires: true, active: true };
const KIM: Person = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: null,
  roles: [], active: true, has_pin: true, pin_locked: false, has_password: false,
};

/** Tab to the row's button, press Enter, and its drawer opens. */
async function opensFromTheKeyboard(path: string, row: RegExp, dialog: string) {
  stubApi((_method, url) => {
    if (url === "/v1/roles") return json(200, { items: [PICKER], total: 1 });
    if (url.startsWith("/v1/competencies")) return json(200, { items: [INDUCTION], total: 1 });
    if (url.startsWith("/v1/people?")) return json(200, { items: [KIM], total: 1 });
    if (url === "/v1/people/LL042") return json(200, KIM);
    if (url === "/v1/people/LL042/overrides") return json(200, []);
    return null;
  });
  renderApp(path);
  const button = await screen.findByRole("button", { name: row });
  for (let i = 0; i < 30 && document.activeElement !== button; i++) await userEvent.tab();
  expect(button).toHaveFocus();
  await userEvent.keyboard("{Enter}");
  expect(await screen.findByRole("dialog", { name: dialog })).toBeInTheDocument();
}

describe("rows open from the keyboard", () => {
  it("on People", () => opensFromTheKeyboard("/people", /^Kim Lee$/, "Kim Lee"));
  it("on Roles", () => opensFromTheKeyboard("/roles", /^Picker/, "Picker"));
  it("on Competencies", () => opensFromTheKeyboard("/competencies", /^Site induction/, "Site induction"));
});
