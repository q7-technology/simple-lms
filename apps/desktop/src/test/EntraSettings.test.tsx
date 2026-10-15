import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Me, Person, Settings } from "../api/types";
import { json, renderApp, stubApi } from "./harness";

const LEIGHTON: Me = {
  id: 1, code: "AD001", name: "Leighton Lauton", email: "leighton@example.com.au", permission: "admin",
  method: "password", scopes: ["*"], idle_seconds: 43200,
};

const SETTINGS: Settings = {
  sign_in_pin: { value: true, source: "default" },
  sign_in_password: { value: true, source: "default" },
  sign_in_entra: { value: true, source: "default", set_up: true },
  quiz_cooldown_tries: { value: 3, source: "default" },
  quiz_cooldown_minutes: { value: 60, source: "default" },
  reminder_days: { value: [30, 14, 0], source: "default" },
  timezone: { value: "Australia/Melbourne", source: "default" },
  daily_hour: { value: 6, source: "default" },
  smtp_host: { value: "", source: "default" },
  smtp_port: { value: 587, source: "default" },
  smtp_user: { value: "", source: "default" },
  smtp_password: { set: false, source: "default" },
  smtp_from: { value: "", source: "default" },
  smtp_security: { value: "starttls", source: "default" },
  public_url: { value: "https://lms.example.com.au", source: "env" },
};

/** Settings as the API has them, for `me`; a PUT answers `put`, or the settings changed. */
function stubSettings(me: Me, settings: Settings = SETTINGS, put?: () => Response) {
  return stubApi((method, url, body) => {
    if (url !== "/v1/settings") return null;
    if (method === "PUT") {
      if (put) return put();
      const now = structuredClone(settings) as unknown as Record<string, unknown>;
      for (const [k, v] of Object.entries(body as Record<string, unknown>)) {
        now[k] = { ...(now[k] as object), value: v, source: "here" };
      }
      return json(200, now);
    }
    return json(200, settings);
  }, me);
}

const puts = (calls: { method: string; url: string; body: unknown }[]) =>
  calls.filter((c) => c.method === "PUT" && c.url === "/v1/settings").map((c) => c.body);

describe("Microsoft in Settings", () => {
  it("switches Microsoft off from a password session; the password stays on", async () => {
    const { calls } = stubSettings(LEIGHTON);
    renderApp("/settings");
    const signIn = await screen.findByRole("region", { name: "Sign-in" });
    const microsoft = await within(signIn).findByLabelText(/Microsoft/);
    expect(microsoft).toBeChecked();
    expect(within(signIn).getByLabelText(/Email and password/)).toBeDisabled();
    expect(within(signIn).getByText("You signed in with an email and password: to switch it off, sign in another way first."))
      .toBeInTheDocument();
    await userEvent.click(microsoft);
    await userEvent.click(within(signIn).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ sign_in_entra: false }]));
  });

  it("switches passwords off from a Microsoft session", async () => {
    const { calls } = stubSettings({ ...LEIGHTON, method: "entra" });
    renderApp("/settings");
    const signIn = await screen.findByRole("region", { name: "Sign-in" });
    expect(await within(signIn).findByLabelText(/Microsoft/)).toBeDisabled();
    await userEvent.click(within(signIn).getByLabelText(/Email and password/));
    await userEvent.click(within(signIn).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ sign_in_password: false }]));
  });

  it("says when Microsoft isn't set up yet", async () => {
    stubSettings(LEIGHTON, { ...SETTINGS, sign_in_entra: { value: true, source: "default", set_up: false } });
    renderApp("/settings");
    const signIn = await screen.findByRole("region", { name: "Sign-in" });
    expect(await within(signIn).findByText(/Microsoft isn't set up yet/)).toBeInTheDocument();
  });

  it("says why a change was refused", async () => {
    stubSettings({ ...LEIGHTON, method: "entra" }, SETTINGS, () => json(409, {
      detail: "Keep email and password or Microsoft sign-in on: it is the only way an admin can sign in (a PIN never opens the desktop).",
      code: "last_way_in" }));
    renderApp("/settings");
    const signIn = await screen.findByRole("region", { name: "Sign-in" });
    await userEvent.click(await within(signIn).findByLabelText(/Email and password/));
    await userEvent.click(within(signIn).getByRole("button", { name: "Save" }));
    expect(await within(signIn).findByRole("alert")).toHaveTextContent("a PIN never opens the desktop");
  });
});

describe("a person who signs in with Microsoft", () => {
  const KIM: Person = {
    id: 4, code: "LL042", name: "Kim Lee", email: "kim@example.com.au", permission: "learner", supervisor: null,
    roles: [], active: true, has_pin: true, pin_locked: false, has_password: false, entra_linked: true,
  };

  it("shows it, and a manager can unlink it", async () => {
    let kim = KIM;
    const { calls } = stubApi((method, url) => {
      if (url.startsWith("/v1/people?")) return json(200, { items: [kim], total: 1 });
      if (url === "/v1/people/LL042") return json(200, kim);
      if (url === "/v1/people/LL042/overrides") return json(200, []);
      if (method === "POST" && url === "/v1/people/LL042/entra/unlink") { kim = { ...KIM, entra_linked: false }; return json(200, kim); }
      if (url === "/v1/roles" || url.startsWith("/v1/competencies")) return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/people");
    expect(await screen.findByRole("cell", { name: "PIN and Microsoft" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Kim Lee" }));
    const drawer = await screen.findByRole("dialog", { name: "Kim Lee" });
    await userEvent.click(await within(drawer).findByRole("button", { name: "Unlink Microsoft" }));
    expect(await within(drawer).findByText("Microsoft account unlinked.")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/v1/people/LL042/entra/unlink")).toBe(true);
    expect(within(drawer).queryByRole("button", { name: "Unlink Microsoft" })).not.toBeInTheDocument();
  });
});
