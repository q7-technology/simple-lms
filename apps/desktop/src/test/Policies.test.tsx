import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Competency, PolicyVersion } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const WHS: Competency = { id: 4, key: "whs-policy", name: "WHS policy", kind: "policy", refresher_months: null, card_expires: true, active: true };
const FORKLIFT: Competency = { id: 2, key: "forklift-licence", name: "Forklift licence", kind: "ticket", refresher_months: null, card_expires: true, active: true };
const V1: PolicyVersion = {
  id: 1, version: 1, body: "Wear your PPE on the floor.", note: null,
  published_by: { code: "MG001", name: "Mel Grant" }, created_at: "2026-09-01T01:00:00Z",
};

describe("competencies", () => {
  it("shows a policy's versions and publishes the next", async () => {
    let versions = [V1];
    const { calls } = stubApi((method, url, body) => {
      if (url === "/v1/competencies") return json(200, { items: [WHS], total: 1 });
      if (url === "/v1/policies/whs-policy/versions") {
        if (method === "POST") {
          versions = [{ ...V1, id: 2, version: 2, ...(body as object) }, ...versions];
          return json(201, versions[0]);
        }
        return json(200, versions);
      }
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    expect(await within(drawer).findByText("Wear your PPE on the floor.")).toBeInTheDocument();
    expect(within(drawer).getByText("Everyone asked for this policy will need to sign version 2.")).toBeInTheDocument();
    await userEvent.type(within(drawer).getByLabelText("The policy's text"), "Wear your PPE, and hi-vis in the yard.");
    await userEvent.type(within(drawer).getByLabelText("What changed (optional)"), "hi-vis in the yard");
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish version 2" }));
    // it can't be undone and everyone signs again: ask once first
    expect(within(drawer).getByText("Publish version 2? Everyone asked for this policy signs again.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      body: "Wear your PPE, and hi-vis in the yard.", note: "hi-vis in the yard" }));
    expect(await within(drawer).findByRole("button", { name: "Publish version 3" })).toBeInTheDocument();
  });

  it("publishes nothing when the manager thinks better of it", async () => {
    const { calls } = stubApi((_m, url) => {
      if (url === "/v1/competencies") return json(200, { items: [WHS], total: 1 });
      if (url === "/v1/policies/whs-policy/versions") return json(200, [V1]);
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    await userEvent.type(await within(drawer).findByLabelText("The policy's text"), "Wear your PPE.");
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish version 2" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Cancel" }));
    expect(within(drawer).queryByText(/signs again/)).not.toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Publish version 2" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("publishes the first version without asking", async () => {
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/competencies") return json(200, { items: [WHS], total: 1 });
      if (url === "/v1/policies/whs-policy/versions") return method === "POST" ? json(201, V1) : json(200, []);
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    await within(drawer).findByText(/No version yet/);
    await userEvent.type(within(drawer).getByLabelText("The policy's text"), "Wear your PPE on the floor.");
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish version 1" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      body: "Wear your PPE on the floor.", note: null }));
  });

  it("asks for a deactivated policy to be reactivated before a new version", async () => {
    stubApi((_m, url) => {
      if (url === "/v1/competencies") return json(200, { items: [{ ...WHS, active: false }], total: 1 });
      if (url === "/v1/policies/whs-policy/versions") return json(200, [V1]);
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    expect(await within(drawer).findByText("Wear your PPE on the floor.")).toBeInTheDocument();
    expect(within(drawer).getByText("Reactivate it to publish a new version.")).toBeInTheDocument();
    expect(within(drawer).queryByLabelText("The policy's text")).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Publish version/ })).not.toBeInTheDocument();
  });

  it("says whether a ticket's card runs out", async () => {
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/competencies") return json(200, { items: [FORKLIFT], total: 1 });
      if (method === "PATCH") return json(200, { ...FORKLIFT, card_expires: false });
      return null;
    });
    renderApp("/competencies");
    await userEvent.click(await screen.findByRole("button", { name: /Forklift licence/ }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence" });
    await userEvent.click(within(drawer).getByLabelText(/The card has an expiry date/));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      name: "Forklift licence", refresher_months: null, card_expires: false }));
  });

  it("shows who signed which version, and their signature", async () => {
    URL.createObjectURL = vi.fn(() => "blob:signature");
    URL.revokeObjectURL = vi.fn();
    const matrix = {
      today: "2026-10-12", competencies: [{ key: "whs-policy", name: "WHS policy", kind: "policy" }],
      people: [{ code: "LL042", name: "Kim Lee", roles: [], supervisor: null,
                 cells: { "whs-policy": { status: "current", granted_on: "2026-10-12", expires_on: null } } }],
    };
    const signed = {
      id: 9, competency: matrix.competencies[0], kind: "granted", granted_on: "2026-10-12", expires_on: null, note: null,
      recorded_by: { code: "LL042", name: "Kim Lee" }, policy_version: 2, signed_name: "Kim Lee", signature: "s-1",
      ticket: null, created_at: "2026-10-12T01:00:00Z",
    };
    stubApi((_m, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, matrix);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, [signed]);
      if (url === "/v1/uploads/s-1") return new Response(new Uint8Array([0x89, 0x50]), { status: 200, headers: { "Content-Type": "image/png" } });
      return null;
    });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee, WHS policy/ }));
    const drawer = await screen.findByRole("dialog", { name: "WHS policy" });
    expect(await within(drawer).findByText("Signed version 2 as “Kim Lee”")).toBeInTheDocument();
    expect(await within(drawer).findByRole("img", { name: "Kim Lee's signature" })).toHaveAttribute("src", "blob:signature");
  });
});
