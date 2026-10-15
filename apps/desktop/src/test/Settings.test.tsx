import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Me, Settings } from "../api/types";
import { json, MEL, renderApp, stubApi } from "./harness";

const LEIGHTON: Me = {
  id: 1, code: "AD001", name: "Leighton Lauton", email: "leighton@example.com.au", permission: "admin",
  method: "password", scopes: ["*"], idle_seconds: 43200,
};

const SETTINGS: Settings = {
  sign_in_pin: { value: true, source: "default" },
  sign_in_password: { value: true, source: "default" },
  sign_in_entra: { value: true, source: "default", set_up: false },
  quiz_cooldown_tries: { value: 3, source: "default" },
  quiz_cooldown_minutes: { value: 60, source: "env" },
  reminder_days: { value: [30, 14, 0], source: "default" },
  timezone: { value: "Australia/Melbourne", source: "env" },
  daily_hour: { value: 6, source: "default" },
  smtp_host: { value: "smtp.example.com.au", source: "here" },
  smtp_port: { value: 587, source: "default" },
  smtp_user: { value: "", source: "default" },
  smtp_password: { set: true, source: "env" },
  smtp_from: { value: "Simple LMS <lms@example.com.au>", source: "here" },
  smtp_security: { value: "starttls", source: "default" },
  public_url: { value: "", source: "default" },
  upload_files_per_day: { value: 30, source: "default" },
  upload_mb_per_day: { value: 200, source: "default" },
  platen_url: { value: "", source: "default" },
  platen_key: { set: false, source: "default" },
  certificate_printer: { value: "office", source: "default" },
  skills_card_printer: { value: "", source: "default" },
};

/** Settings as the API has them; a PUT answers `put` (or the settings, changed). */
function stubSettings(put?: (body: Record<string, unknown>) => Response) {
  let now = structuredClone(SETTINGS);
  return stubApi((method, url, body) => {
    if (url === "/v1/settings" && method === "GET") return json(200, now);
    if (url === "/v1/settings" && method === "PUT") {
      if (put) return put(body as Record<string, unknown>);
      now = structuredClone(now);
      for (const [k, v] of Object.entries(body as Record<string, unknown>)) {
        if (k === "smtp_password") now.smtp_password = { set: v !== "", source: "here" };
        else if (k === "platen_key") now.platen_key = { set: v !== "", source: "here" };
        else (now as unknown as Record<string, unknown>)[k] = { value: v, source: "here" };
      }
      return json(200, now);
    }
    if (url === "/v1/settings/test-email") return json(202, { to: "leighton@example.com.au" });
    if (url.startsWith("/v1/matrix")) return json(200, { today: "2026-10-12", competencies: [], people: [] });
    if (url === "/v1/roles") return json(200, { items: [], total: 0 });
    return null;
  }, LEIGHTON);
}

const section = (name: string) => screen.findByRole("region", { name });
const puts = (calls: { method: string; url: string; body: unknown }[]) =>
  calls.filter((c) => c.method === "PUT" && c.url === "/v1/settings").map((c) => c.body);

describe("settings", () => {
  it("is linked for an admin only", async () => {
    stubSettings();
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("is not linked, nor shown, for a manager", async () => {
    stubApi((_m, url) => (url.startsWith("/v1/matrix") ? json(200, { today: "2026-10-12", competencies: [], people: [] })
      : url === "/v1/roles" ? json(200, { items: [], total: 0 }) : null), MEL);
    renderApp("/settings");
    expect(await screen.findByText("Only an admin can change the settings.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
  });

  it("says where each value comes from", async () => {
    stubSettings();
    renderApp("/settings");
    const quizzes = await section("Quizzes");
    expect(await within(quizzes).findByLabelText(/Failed tries in a row/)).toHaveValue(3);
    expect(within(quizzes).getByText("Default")).toBeInTheDocument();
    expect(within(quizzes).getByText("From .env")).toBeInTheDocument();
    const email = await section("Email");
    expect(within(email).getAllByText("Set here").length).toBeGreaterThan(0);
  });

  it("saves a section's changes, and only those", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const quizzes = await section("Quizzes");
    const tries = await within(quizzes).findByLabelText(/Failed tries in a row/);
    await userEvent.clear(tries);
    await userEvent.type(tries, "5");
    await userEvent.click(within(quizzes).getByRole("button", { name: "Save" }));
    expect(await within(quizzes).findByRole("status")).toHaveTextContent("Saved.");
    expect(puts(calls)).toEqual([{ quiz_cooldown_tries: 5 }]);
    expect(within(quizzes).getAllByText("Set here").length).toBe(1);
  });

  it("takes reminder days as a list", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const reminders = await section("Reminders");
    const days = await within(reminders).findByLabelText(/Reminder days/);
    expect(days).toHaveValue("30, 14, 0");
    await userEvent.clear(days);
    await userEvent.type(days, "60, 30 7,0");
    await userEvent.selectOptions(within(reminders).getByLabelText(/Daily job/), "7");
    await userEvent.click(within(reminders).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ reminder_days: [60, 30, 7, 0], daily_hour: 7 }]));
  });

  it("shows the API's problem on its field", async () => {
    stubSettings(() => json(422, { errors: [{ field: "timezone", message: "'Australia/Ballarat' is not a time zone, e.g. Australia/Melbourne" }] }));
    renderApp("/settings");
    const reminders = await section("Reminders");
    const zone = await within(reminders).findByLabelText(/Time zone/);
    await userEvent.clear(zone);
    await userEvent.type(zone, "Australia/Ballarat");
    await userEvent.click(within(reminders).getByRole("button", { name: "Save" }));
    expect(await within(reminders).findByText("'Australia/Ballarat' is not a time zone, e.g. Australia/Melbourne")).toBeInTheDocument();
    expect(within(reminders).queryByRole("status")).not.toBeInTheDocument();
  });

  it("never shows the email password, and can clear it", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const email = await section("Email");
    const password = await within(email).findByLabelText(/Password/);
    expect(password).toHaveValue("");
    expect(within(email).getByText(/A password is set/)).toBeInTheDocument();
    // blank keeps it: only the change goes
    const port = within(email).getByLabelText(/Port/);
    await userEvent.clear(port);
    await userEvent.type(port, "465");
    await userEvent.selectOptions(within(email).getByLabelText(/Security/), "ssl");
    await userEvent.click(within(email).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ smtp_port: 465, smtp_security: "ssl" }]));
    await userEvent.type(password, "app password");
    await userEvent.click(within(email).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls).at(-1)).toEqual({ smtp_password: "app password" }));
    expect(password).toHaveValue("");
    await userEvent.click(within(email).getByRole("button", { name: "Clear the password" }));
    await waitFor(() => expect(puts(calls).at(-1)).toEqual({ smtp_password: "" }));
    expect(await within(email).findByText(/No password/)).toBeInTheDocument();
  });

  it("sends a test email to the admin", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const email = await section("Email");
    await userEvent.click(await within(email).findByRole("button", { name: "Send a test email" }));
    expect(await within(email).findByText(/Test email on its way to leighton@example.com.au/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/settings/test-email")).toBe(true);
  });

  it("switches PIN sign-in off; password sign-in stays on", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const signIn = await section("Sign-in");
    const pin = await within(signIn).findByLabelText(/Code and PIN/);
    expect(pin).toBeChecked();
    expect(within(signIn).getByLabelText(/Email and password/)).toBeDisabled();
    expect(within(signIn).getByText(/the only way an admin can sign in/)).toBeInTheDocument();
    await userEvent.click(pin);
    await userEvent.click(within(signIn).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ sign_in_pin: false }]));
  });

  it("sets where certificates and skills cards print, the key never shown", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const printing = await section("Printing");
    await userEvent.type(within(printing).getByLabelText(/Platen's address/), "https://platen.example.com.au/intake/jobs");
    await userEvent.type(within(printing).getByLabelText(/Platen key/), "pk_s3cret");
    await userEvent.clear(within(printing).getByLabelText(/Certificates print on/));
    await userEvent.type(within(printing).getByLabelText(/Certificates print on/), "front office");
    await userEvent.click(within(printing).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{
      platen_url: "https://platen.example.com.au/intake/jobs", platen_key: "pk_s3cret", certificate_printer: "front office",
    }]));
    expect(await within(printing).findByText("A key is set. Leave this empty to keep it.")).toBeInTheDocument();
    expect(within(printing).getByLabelText(/Platen key/)).toHaveValue("");
  });

  it("puts a value back to .env or the default", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const web = await section("Web address");
    const url = await within(web).findByLabelText(/Web address/);
    await userEvent.type(url, "https://lms.example.com.au");
    await userEvent.click(within(web).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ public_url: "https://lms.example.com.au" }]));
    await userEvent.click(await within(web).findByRole("button", { name: /Use .env or the default/ }));
    await waitFor(() => expect(puts(calls).at(-1)).toEqual({ public_url: null }));
  });

  it("sets how much a person can send in a day", async () => {
    const { calls } = stubSettings();
    renderApp("/settings");
    const up = await section("Uploads");
    const files = await within(up).findByLabelText("Files a person can send in a day");
    const mb = within(up).getByLabelText("MB a person can send in a day");
    expect(files).toHaveValue(30);
    expect(mb).toHaveValue(200);
    await userEvent.clear(mb);
    await userEvent.type(mb, "500");
    await userEvent.click(within(up).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(calls)).toEqual([{ upload_mb_per_day: 500 }]));
  });
});
