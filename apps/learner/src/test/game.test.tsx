import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Module } from "../api/types";
import { GAME_PREFS_KEY, getGamePrefs, reloadGamePrefs } from "../lib/game";
import { json, KIM, listen, renderApp, stubApi } from "./harness";

const item = (key: string, name: string, status: string) =>
  ({ key, name, kind: "module", status, granted_on: null, expires_on: null, card_expires: null, waiting: false });
const training = (...items: ReturnType<typeof item>[]) => ({ person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12", items });

const INDUCTION: Module = {
  key: "site-induction", name: "Site induction", resume_at: 1, retry_at: null, retry_at_text: null,
  version: {
    id: 1, version: 1, pass_mark: 80,
    pages: [{ kind: "text", title: "Welcome", body: "Sign in at the gatehouse.", url: null, file: null }],
    questions: [{ prompt: "Where do you sign in?", options: ["The gatehouse", "The canteen"] }],
  },
};
const ATTEMPT = { id: 1, version: 1, correct: 1, total: 1, score: 100, pass_mark: 80, passed: true, created_at: "2026-10-12T01:00:00Z", retry_at: null, retry_at_text: null };

/** The site induction's quiz, answered right or wrong. */
async function handIn(passed: boolean) {
  stubApi((method, url) => {
    if (url === "/v1/people/LL042/training") return json(200, training(item("site-induction", "Site induction", "missing")));
    if (url === "/v1/modules/site-induction") return json(200, INDUCTION);
    if (method === "POST" && url === "/v1/modules/site-induction/attempts") {
      return json(201, passed ? ATTEMPT : { ...ATTEMPT, correct: 0, score: 0, passed: false });
    }
    return null;
  });
  renderApp(KIM, Date.now(), "/module/site-induction");
  await userEvent.click(await screen.findByLabelText(passed ? "The gatehouse" : "The canteen"));
  await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
  await screen.findByRole("status", { name: passed ? "Passed" : "Not passed" });
}

describe("game touches in the learner app", () => {
  it("dings out loud on a pass, woken by the tap that handed it in", async () => {
    const heard = listen();
    await handIn(true);
    expect(heard.woken).toBe(1);
    expect(heard.notes).toBe(2);
  });

  it("stays quiet on a fail", async () => {
    const heard = listen();
    await handIn(false);
    expect(heard.notes).toBe(0);
  });

  it("keeps the sound on when what is kept can't be read", () => {
    window.localStorage.setItem(GAME_PREFS_KEY, "{not json");
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ sound: true });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("private mode"); });
    reloadGamePrefs();
    expect(getGamePrefs()).toEqual({ sound: true });
  });

  it("shows how much is done as a ring", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training"
      ? json(200, training(item("a", "Fire safety", "current"), item("b", "Site induction", "missing"),
                           item("c", "Manual handling", "expiring"))) : null);
    renderApp(KIM);
    expect(await screen.findByText("1 of 3 done")).toBeInTheDocument();
    expect(screen.getByText("2 to go")).toBeInTheDocument();
  });

  it("says all done when it is", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(200, training(item("a", "Fire safety", "current"))) : null);
    renderApp(KIM);
    expect(await screen.findByText("1 of 1 done")).toBeInTheDocument();
    expect(screen.getByText("All done. Nice work.")).toBeInTheDocument();
  });

  it("turns the sound off in one tap on My training, for this device", async () => {
    const heard = listen();
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(200, training(item("a", "Fire safety", "current"))) : null);
    const { unmount } = renderApp(KIM);
    const sound = await screen.findByRole("button", { name: "Sound" });
    expect(sound).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(sound);
    expect(sound).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(GAME_PREFS_KEY)).toBe('{"sound":false}');
    unmount();
    await handIn(true);
    expect(within(screen.getByRole("status", { name: "Passed" })).getByText("Ding!")).toBeInTheDocument();
    expect(heard.notes).toBe(0);
    expect(heard.woken).toBe(0);
  });
});
