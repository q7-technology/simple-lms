import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Delivery, Webhook } from "../api/types";
import { GAME_PREFS_KEY } from "../lib/gamePrefs";
import { ADA, ALL_SETTINGS, json, renderApp, stubApi } from "./harness";

const TMS: Webhook = {
  id: 1, name: "Simple TMS", url: "https://tms.example.com.au/lms-events",
  events: ["competency.granted", "competency.revoked"], active: true, waiting: 0, failed: 1,
  created_at: "2026-10-12T01:00:00Z",
};
const FAILED: Delivery = {
  id: 9, event_id: "1b4e28ba-2fa1-41d2-883f-0016d3cca427", event_type: "competency.granted", status: "failed",
  attempts: 5, next_attempt_at: "2026-10-12T05:00:00Z", last_error: "HTTP 503: not now", done_at: null,
  created_at: "2026-10-12T01:30:00Z",
};

/** Settings with these webhooks, and no API keys yet. */
function hooks(list: Webhook[], more: (method: string, url: string, body: unknown) => Response | null = () => null) {
  return stubApi((method, url, body) => {
    if (method === "GET" && url === "/v1/settings") return json(200, ALL_SETTINGS);
    if (method === "GET" && url === "/v1/webhooks") return json(200, list);
    if (method === "GET" && url === "/v1/api-keys") return json(200, []);
    return more(method, url, body);
  }, ADA);
}

describe("webhooks", () => {
  it("adds one and shows its secret once", async () => {
    let list: Webhook[] = [];
    const { calls } = hooks(list, (method, url) => {
      if (method === "POST" && url === "/v1/webhooks") {
        list = [TMS];
        return json(201, { ...TMS, failed: 0, secret: "whsec_s3cret" });
      }
      return null;
    });
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Add a webhook" });
    await userEvent.type(within(form).getByLabelText("Name"), "Simple TMS");
    await userEvent.type(within(form).getByLabelText("Address"), "https://tms.example.com.au/lms-events");
    await userEvent.click(within(form).getByLabelText("Granted"));
    await userEvent.click(within(form).getByLabelText("Revoked"));
    await userEvent.click(within(form).getByRole("button", { name: "Add webhook" }));

    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Simple TMS", url: "https://tms.example.com.au/lms-events",
      events: ["competency.granted", "competency.revoked"],
    });
    expect(await screen.findByLabelText("Simple TMS's secret")).toHaveValue("whsec_s3cret");
    expect(screen.getByText(/Simple LMS won't show it again/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByLabelText("Simple TMS's secret")).not.toBeInTheDocument();
  });

  it("says plainly what is wrong with an address", async () => {
    hooks([], (method, url) => method === "POST" && url === "/v1/webhooks"
      ? json(422, { errors: [{ field: "url", message: "an internal address: a webhook goes to a public one" }] }) : null);
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Add a webhook" });
    await userEvent.type(within(form).getByLabelText("Name"), "Local");
    await userEvent.type(within(form).getByLabelText("Address"), "http://localhost:9000/hook");
    await userEvent.click(within(form).getByLabelText("Granted"));
    await userEvent.click(within(form).getByRole("button", { name: "Add webhook" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("Address: an internal address");
  });

  it("sends everything as a star", async () => {
    const { calls } = hooks([], (method, url) =>
      method === "POST" && url === "/v1/webhooks" ? json(201, { ...TMS, events: ["*"], secret: "whsec_x" }) : null);
    renderApp("/settings");
    const form = await screen.findByRole("form", { name: "Add a webhook" });
    await userEvent.type(within(form).getByLabelText("Name"), "Everything");
    await userEvent.type(within(form).getByLabelText("Address"), "https://hooks.example.com.au/lms");
    await userEvent.click(within(form).getByLabelText("Everything, and whatever is added later"));
    expect(within(form).getByLabelText("Granted")).toBeDisabled();
    await userEvent.click(within(form).getByRole("button", { name: "Add webhook" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ events: ["*"] }));
  });

  it("changes one's events and turns it off", async () => {
    const { calls } = hooks([TMS], (method, url, body) => {
      if (url === "/v1/webhooks/1/deliveries") return json(200, []);
      if (method === "PATCH" && url === "/v1/webhooks/1") return json(200, { ...TMS, ...(body as object) });
      return null;
    });
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("button", { name: "Simple TMS" }));
    const drawer = await screen.findByRole("dialog", { name: "Simple TMS" });
    await userEvent.click(within(drawer).getByLabelText("Lapsed"));
    await userEvent.click(within(drawer).getByLabelText("On: events are sent to it"));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    // turning it off gives up what is waiting: asked first, in place
    expect(within(drawer).getByText(/Turn Simple TMS off\? What is waiting for it is given up on/)).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Keep it on" }));
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.click(within(drawer).getByRole("button", { name: "Save" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Turn it off" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      name: "Simple TMS", url: TMS.url, events: ["competency.granted", "competency.revoked", "competency.lapsed"],
      active: false,
    }));
    expect(await within(drawer).findByText("Saved.")).toBeInTheDocument();
  });

  it("lists how its deliveries went and sends a failed one again", async () => {
    let deliveries = [FAILED];
    const { calls } = hooks([TMS], (method, url) => {
      if (url === "/v1/webhooks/1/deliveries") return json(200, deliveries);
      if (method === "POST" && url === "/v1/webhooks/1/deliveries/9/retry") {
        deliveries = [{ ...FAILED, status: "pending", attempts: 0 }];
        return json(200, deliveries[0]);
      }
      return null;
    });
    renderApp("/settings");
    expect(await screen.findByText("1 failed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Simple TMS" }));
    const drawer = await screen.findByRole("dialog", { name: "Simple TMS" });
    const row = (await within(drawer).findByText("competency.granted")).closest("li")!;
    expect(within(row).getByText("Failed")).toBeInTheDocument();
    expect(within(row).getByText(/HTTP 503: not now/)).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Send again" }));
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/webhooks/1/deliveries/9/retry")).toBe(true);
    expect(await within(drawer).findByText("Waiting")).toBeInTheDocument();
  });

  it("makes a new secret and shows it once", async () => {
    hooks([TMS], (method, url) => {
      if (url === "/v1/webhooks/1/deliveries") return json(200, []);
      if (method === "POST" && url === "/v1/webhooks/1/secret") return json(200, { secret: "whsec_new" });
      return null;
    });
    renderApp("/settings");
    await userEvent.click(await screen.findByRole("button", { name: "Simple TMS" }));
    const drawer = await screen.findByRole("dialog", { name: "Simple TMS" });
    await userEvent.click(within(drawer).getByRole("button", { name: "New secret" }));
    expect(await within(drawer).findByLabelText("Simple TMS's secret")).toHaveValue("whsec_new");
  });

  it("is on the Settings page with Game Mode off too", async () => {
    window.localStorage.setItem(GAME_PREFS_KEY, '{"classroom":false}');
    hooks([TMS], (_m, url) => (url === "/v1/webhooks/1/deliveries" ? json(200, []) : null));
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Back to the classroom" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Simple TMS" }));
    expect(await screen.findByRole("dialog", { name: "Simple TMS" })).toBeInTheDocument();
  });
});
