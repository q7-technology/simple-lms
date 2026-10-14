import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, KIM, renderApp, stubApi } from "./harness";

const TRAINING = {
  person: { code: "LL042", name: "Kim Lee" },
  today: "2026-10-12",
  items: [
    { key: "first-aid", name: "First aid", kind: "ticket", status: "lapsed", granted_on: "2023-09-30", expires_on: "2026-09-30" },
    { key: "forklift-licence", name: "Forklift licence", kind: "ticket", status: "current", granted_on: "2026-03-01", expires_on: "2031-03-01" },
    { key: "site-induction", name: "Site induction", kind: "module", status: "expiring", granted_on: "2024-11-01", expires_on: "2026-11-01" },
    { key: "whs-policy", name: "WHS policy", kind: "policy", status: "missing", granted_on: null, expires_on: null },
  ],
};

function answers(_method: string, url: string) {
  if (url === "/v1/auth/pin-login") return json(200, { token: "lms_s.kim", person: KIM });
  if (url === "/v1/people/LL042/training") return json(200, TRAINING);
  if (url === "/v1/auth/logout") return new Response(null, { status: 204 });
  return null;
}

describe("the learner app", () => {
  it("signs in with a code and PIN and shows My training in three parts", async () => {
    const calls = stubApi(answers);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Your code"), "ll042");
    await userEvent.type(screen.getByLabelText("PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    expect(calls[0].body).toEqual({ code: "ll042", pin: "2468" });

    const overdue = await screen.findByRole("region", { name: "Overdue" });
    expect(within(overdue).getAllByText(/First aid|WHS policy/).map((e) => e.textContent)).toEqual(["First aid", "WHS policy"]);
    expect(within(overdue).getByText("Ran out after 30 Sep 2026")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Due soon" })).getByText("Due by 1 Nov 2026")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Done" })).getByText("Forklift licence")).toBeInTheDocument();
  });

  it("can sign in with an email and password instead", async () => {
    const calls = stubApi((method, url) => url === "/v1/auth/login"
      ? json(200, { token: "lms_s.kim", person: { ...KIM, method: "password", idle_seconds: 43200 } })
      : answers(method, url));
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with email and password" }));
    await userEvent.type(screen.getByLabelText("Email"), "kim@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    expect(calls[0]).toMatchObject({ url: "/v1/auth/login", body: { email: "kim@example.com" } });
  });

  it("says when the PIN is wrong or locked", async () => {
    let code = "wrong_pin";
    stubApi((_m, url) => url === "/v1/auth/pin-login"
      ? json(401, { detail: "this PIN is locked after too many wrong tries; ask your manager to reset it", code }) : null);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Your code"), "LL042");
    await userEvent.type(screen.getByLabelText("PIN"), "0000");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong code or PIN.");
    code = "locked";
    await userEvent.type(screen.getByLabelText("PIN"), "0000");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This PIN is locked after too many wrong tries; ask your manager to reset it.");
  });

  it("goes back to sign-in when the API ends the session", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(401, { detail: "session expired or invalid" }) : null);
    renderApp(KIM);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.localStorage.getItem("lms.learner.session")).toBeNull();
  });

  it("forgets whoever left the tablet alone for 15 minutes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      stubApi(answers);
      renderApp(KIM);
      expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
      await act(async () => { vi.advanceTimersByTime(14 * 60_000); });
      expect(screen.getByRole("heading", { name: "My training" })).toBeInTheDocument();
      await act(async () => { vi.advanceTimersByTime(2 * 60_000); });
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not pick up a session left idle too long", async () => {
    stubApi(answers);
    renderApp(KIM, Date.now() - 16 * 60_000);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(window.localStorage.getItem("lms.learner.session")).toBeNull();
  });

  it("does not let the next person's tap keep the last person signed in", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      stubApi(answers);
      renderApp(KIM);
      expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
      // the tablet slept, so the check never ran; then someone taps it
      vi.setSystemTime(Date.now() + 16 * 60_000);
      await act(async () => { window.dispatchEvent(new Event("pointerdown")); });
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
      expect(screen.queryByText("First aid")).toBeNull();
      expect(window.localStorage.getItem("lms.learner.session")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("forgets the last person as soon as a sleeping tablet wakes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      stubApi(answers);
      renderApp(KIM);
      expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
      vi.setSystemTime(Date.now() + 16 * 60_000);
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says something plain when signing in fails without a reason", async () => {
    stubApi((_m, url) => url === "/v1/auth/pin-login" ? json(401, {}) : null);
    renderApp();
    await userEvent.type(await screen.findByLabelText("Your code"), "LL042");
    await userEvent.type(screen.getByLabelText("PIN"), "0000");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong code or PIN.");
  });

  it("keeps a code and PIN out of the browser's saved passwords", async () => {
    stubApi(answers);
    renderApp();
    expect(await screen.findByLabelText("Your code")).toHaveAttribute("autocomplete", "off");
    expect(screen.getByLabelText("PIN")).toHaveAttribute("autocomplete", "one-time-code");
  });

  it("drops the session at once when another tab signs out", async () => {
    stubApi(answers);
    renderApp(KIM);
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    window.localStorage.removeItem("lms.learner.session");
    act(() => { window.dispatchEvent(new StorageEvent("storage", { key: "lms.learner.session", newValue: null })); });
    expect(await screen.findByLabelText("Your code")).toBeInTheDocument();
    expect(screen.queryByText("First aid")).not.toBeInTheDocument();
  });

  it("counts a tap in another tab as activity here", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const start = Date.now();
      stubApi(answers);
      renderApp(KIM, start);
      expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
      // ten minutes on, the other tab is tapped; ten more and this tab checks
      const stored = JSON.parse(window.localStorage.getItem("lms.learner.session")!);
      window.localStorage.setItem("lms.learner.session", JSON.stringify({ ...stored, active_at: start + 10 * 60_000 }));
      vi.setSystemTime(start + 20 * 60_000);
      act(() => { vi.advanceTimersByTime(15_000); });
      expect(screen.getByRole("heading", { name: "My training" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says plainly when Simple LMS isn't answering", async () => {
    stubApi((method, url) => url === "/v1/people/LL042/training" ? json(500, {}) : answers(method, url));
    renderApp(KIM);
    expect(await screen.findByRole("alert")).toHaveTextContent("Simple LMS isn't answering right now.");
  });

  it("puts a refusal in plain words, never a bare status", async () => {
    stubApi((method, url) => url === "/v1/people/LL042/training" ? json(403, {}) : answers(method, url));
    renderApp(KIM);
    expect(await screen.findByRole("alert")).toHaveTextContent("That didn't work. Try again, or ask your manager.");
  });
});
