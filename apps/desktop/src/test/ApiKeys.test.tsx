import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ApiKey } from "../api/types";
import { ADA, ALL_SETTINGS, json, renderApp, stubApi } from "./harness";

const TMS: ApiKey = {
  id: 3, name: "Simple TMS", prefix: "lms_k.Ab3d", scopes: ["competencies:read"],
  created_by: { code: "AD001", name: "Ada Admin" }, created_at: "2026-10-12T01:00:00Z",
  last_used_at: "2026-10-12T03:15:00Z", revoked_at: null,
};

/** Settings with these keys, and no webhooks yet. */
function keys(list: () => ApiKey[], more: (method: string, url: string) => Response | null = () => null) {
  return stubApi((method, url) => {
    if (method === "GET" && url === "/v1/settings") return json(200, ALL_SETTINGS);
    if (method === "GET" && url === "/v1/webhooks") return json(200, []);
    if (method === "GET" && url === "/v1/api-keys") return json(200, list());
    return more(method, url);
  }, ADA);
}

describe("API keys", () => {
  it("makes one for another system and shows it once", async () => {
    let list: ApiKey[] = [];
    const { calls } = keys(() => list, (method, url) => {
      if (method === "POST" && url === "/v1/api-keys") {
        list = [TMS];
        return json(201, { ...TMS, key: "lms_k.Ab3dEfGh" });
      }
      return null;
    });
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Make an API key" });
    expect(within(form).getByLabelText("Read who is current (the competency API)")).toBeChecked();
    await userEvent.type(within(form).getByLabelText("Who it is for"), "Simple TMS");
    await userEvent.click(within(form).getByRole("button", { name: "Make key" }));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Simple TMS", scopes: ["competencies:read"] });
    expect(await screen.findByLabelText("Simple TMS's key")).toHaveValue("lms_k.Ab3dEfGh");
    expect(screen.getByText(/Copy it now: Simple LMS won't show it again/)).toBeInTheDocument();
    const row = await screen.findByRole("row", { name: /Simple TMS/ });
    expect(within(row).getByText("lms_k.Ab3d…")).toBeInTheDocument();
  });

  it("asks once before revoking one", async () => {
    let list = [TMS];
    const { calls } = keys(() => list, (method, url) => {
      if (method === "POST" && url === "/v1/api-keys/3/revoke") {
        list = [{ ...TMS, revoked_at: "2026-10-12T04:00:00Z" }];
        return json(200, list[0]);
      }
      return null;
    });
    renderApp("/settings");
    const row = await screen.findByRole("row", { name: /Simple TMS/ });
    await userEvent.click(within(row).getByRole("button", { name: "Revoke" }));
    expect(screen.getByText("Revoke Simple TMS's key? Anything using it stops working, for good.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(row).getByRole("button", { name: "Revoke" }));
    await userEvent.click(screen.getByRole("button", { name: "Revoke it" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/api-keys/3/revoke")).toBe(true));
    expect(await within(await screen.findByRole("row", { name: /Simple TMS/ })).findByText("Revoked")).toBeInTheDocument();
  });
});
