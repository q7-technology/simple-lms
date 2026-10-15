import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Person } from "../api/types";
import { MEL, json, renderApp, stubApi } from "./harness";

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

  it("doesn't offer you a new permission or deactivation on your own record", async () => {
    const me = { ...MEL, code: "AD001", name: "Ada Admin", permission: "admin" as const };
    const ada: Person = { ...SAM, id: 1, code: "AD001", name: "Ada Admin", permission: "admin" };
    stubApi((_method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [ada, KIM], total: 2 });
      if (url === "/v1/people/AD001") return json(200, ada);
      if (url === "/v1/people/AD001/overrides") return json(200, []);
      if (url === "/v1/roles" || url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      return null;
    }, me);
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Ada Admin" }));
    const drawer = await screen.findByRole("dialog", { name: "Ada Admin" });
    expect(await within(drawer).findByText("You can't change your own permission or deactivate yourself.")).toBeInTheDocument();
    expect(within(drawer).queryByLabelText("Permission")).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  });

  it("warns before a new password of your own signs you out, then signs you out", async () => {
    const me = { ...MEL, code: "AD001", name: "Ada Admin", permission: "admin" as const };
    const ada: Person = { ...SAM, id: 1, code: "AD001", name: "Ada Admin", permission: "admin" };
    const { calls } = stubApi((method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [ada], total: 1 });
      if (url === "/v1/people/AD001") return json(200, ada);
      if (url === "/v1/people/AD001/overrides") return json(200, []);
      if (url === "/v1/people/AD001/password" && method === "POST") return json(200, ada);
      if (url === "/v1/roles" || url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      return null;
    }, me);
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Ada Admin" }));
    const drawer = await screen.findByRole("dialog", { name: "Ada Admin" });
    await userEvent.type(await within(drawer).findByLabelText("New password"), "a long enough password");
    await userEvent.click(within(drawer).getByRole("button", { name: "Set password" }));
    expect(within(drawer).getByText("Setting a new password signs you out here: sign in again with the new one."))
      .toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/password"))).toBe(false);

    await userEvent.click(within(drawer).getByRole("button", { name: "Cancel" }));
    expect(within(drawer).queryByText(/signs you out here/)).not.toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Set password" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Set password and sign out" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/sign-in"));
    expect(calls.find((c) => c.url === "/v1/people/AD001/password")?.body).toEqual({ password: "a long enough password" });
    expect(calls.some((c) => c.url === "/v1/auth/logout")).toBe(true);
  });

  it("warns before a new PIN only when you signed in with your PIN", async () => {
    const ada: Person = { ...SAM, id: 1, code: "AD001", name: "Ada Admin", permission: "admin" };
    const stub = (method: string, url: string) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [ada], total: 1 });
      if (url === "/v1/people/AD001") return json(200, ada);
      if (url === "/v1/people/AD001/overrides") return json(200, []);
      if (url === "/v1/people/AD001/pin" && method === "POST") return json(200, ada);
      if (url === "/v1/roles" || url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      return null;
    };
    // signed in with a password: a new PIN leaves this session be
    stubApi(stub, { ...MEL, code: "AD001", name: "Ada Admin", permission: "admin" });
    const first = renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Ada Admin" }));
    let drawer = await screen.findByRole("dialog", { name: "Ada Admin" });
    await userEvent.type(await within(drawer).findByLabelText("New PIN"), "2468");
    await userEvent.click(within(drawer).getByRole("button", { name: "Set PIN" }));
    expect(await within(drawer).findByText("PIN set.")).toBeInTheDocument();
    first.unmount();

    stubApi(stub, { ...MEL, code: "AD001", name: "Ada Admin", permission: "admin", method: "pin" });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Ada Admin" }));
    drawer = await screen.findByRole("dialog", { name: "Ada Admin" });
    await userEvent.type(await within(drawer).findByLabelText("New PIN"), "2468");
    await userEvent.click(within(drawer).getByRole("button", { name: "Set PIN" }));
    expect(within(drawer).getByText("Setting a new PIN signs you out here: sign in again with the new one."))
      .toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Set PIN and sign out" }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/sign-in"));
  });

  it("keeps a PIN and a note typed in until they save", async () => {
    let refuse = true;
    stubApi((method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [KIM], total: 1 });
      if (url === "/v1/people/LL042") return json(200, KIM);
      if (url === "/v1/people/LL042/overrides") {
        return method === "POST" ? json(422, { errors: [{ field: "note", message: "too short" }] }) : json(200, []);
      }
      if (url === "/v1/people/LL042/pin") {
        return refuse ? json(422, { errors: [{ field: "pin", message: "too easy to guess" }] }) : json(200, KIM);
      }
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/competencies")) {
        return json(200, { items: [{ id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: null, active: true }], total: 1 });
      }
      return null;
    });
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee" }));
    const drawer = await screen.findByRole("dialog", { name: "Kim Lee" });

    const pin = await within(drawer).findByLabelText("New PIN");
    await userEvent.type(pin, "1111");
    await userEvent.click(within(drawer).getByRole("button", { name: "Set PIN" }));
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("pin: too easy to guess");
    expect(pin).toHaveValue("1111");
    refuse = false;
    await userEvent.click(within(drawer).getByRole("button", { name: "Set PIN" }));
    expect(await within(drawer).findByText("PIN set.")).toBeInTheDocument();
    expect(pin).toHaveValue("");

    await userEvent.selectOptions(within(drawer).getByLabelText("Competency"), "site-induction");
    await userEvent.type(within(drawer).getByLabelText("Note"), "x");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("note: too short");
    expect(within(drawer).getByLabelText("Note")).toHaveValue("x");
  });
});
