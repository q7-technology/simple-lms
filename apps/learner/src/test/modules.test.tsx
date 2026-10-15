import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Module } from "../api/types";
import { json, KIM, renderApp, stubApi, type Call } from "./harness";

const TRAINING = {
  person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12",
  items: [{ key: "site-induction", name: "Site induction", kind: "module", status: "missing", granted_on: null,
            expires_on: null, card_expires: true, waiting: false }],
};
const link = (id: string) => `/v1/media/${id}?session=1&expires=1&sig=x`;
const INDUCTION: Module = {
  key: "site-induction", name: "Site induction", resume_at: 0,
  version: {
    id: 1, version: 1, pass_mark: 80,
    pages: [
      { kind: "text", title: "Welcome", body: "Sign in at the gatehouse.", url: null, file: null },
      { kind: "image", title: "The yard", body: "Walk inside the green lines.", url: null,
        file: { id: "i-1", content_type: "image/jpeg", size_bytes: 1000, link: link("i-1") } },
      { kind: "pdf", title: "Site map", body: null, url: null,
        file: { id: "p-1", content_type: "application/pdf", size_bytes: 1000, link: link("p-1") } },
      { kind: "video", title: "Lifting safely", body: null, url: null,
        file: { id: "v-1", content_type: "video/mp4", size_bytes: 1000, link: link("v-1") } },
      { kind: "link", title: "SafeWork", body: "Read about lifting.", url: "https://www.safework.nsw.gov.au", file: null },
    ],
    questions: [
      { prompt: "Where do you sign in?", options: ["The gatehouse", "The canteen"] },
      { prompt: "What do you wear on the floor?", options: ["Thongs", "Your PPE", "Anything"] },
    ],
  },
};
const PASS = { id: 1, version: 1, correct: 2, total: 2, score: 100, pass_mark: 80, passed: true, created_at: "2026-10-12T01:00:00Z" };
const FAIL = { ...PASS, correct: 1, score: 50, passed: false };

/** The site induction, opened at `resume_at`; `attempts` answer the quiz in turn. */
function stubModule(module: Module = INDUCTION, attempts: Response[] = [json(201, PASS)]) {
  return stubApi((method, url) => {
    if (url === "/v1/people/LL042/training") return json(200, TRAINING);
    if (url === "/v1/modules/site-induction") return json(200, module);
    if (method === "PUT" && url === "/v1/modules/site-induction/progress") return new Response(null, { status: 204 });
    if (method === "POST" && url === "/v1/modules/site-induction/attempts") return attempts.shift() ?? null;
    if (url === "/v1/auth/me") return json(200, KIM);
    return null;
  });
}

const method204 = (method: string) => (method === "PUT" ? new Response(null, { status: 204 }) : null);
const places = (calls: Call[]) => calls.filter((c) => c.method === "PUT").map((c) => c.body);

describe("the module player", () => {
  it("opens from My training and shows one page at a time, keeping the place", async () => {
    const calls = stubModule();
    renderApp(KIM);
    await userEvent.click(await screen.findByRole("link", { name: "Start the module: Site induction" }));
    expect(await screen.findByRole("article", { name: "Welcome" })).toHaveTextContent("Sign in at the gatehouse.");
    expect(screen.getByLabelText("Page 1 of 5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("img", { name: "The yard" })).toHaveAttribute("src", link("i-1"));
    expect(screen.getByText("Walk inside the green lines.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("link", { name: "Open the PDF (downloads the PDF)" })).toHaveAttribute("href", link("p-1"));

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("Lifting safely")).toHaveAttribute("src", link("v-1"));

    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    const safework = screen.getByRole("link", { name: /Open SafeWork/ });
    expect(safework).toHaveAttribute("href", "https://www.safework.nsw.gov.au");
    expect(safework).toHaveAttribute("target", "_blank");
    expect(safework.getAttribute("rel")).toContain("noopener");

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Page 4 of 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Start the quiz" }));
    expect(await screen.findByRole("heading", { name: "The quiz" })).toBeInTheDocument();
    await waitFor(() => expect(places(calls)).toEqual([1, 2, 3, 4, 3, 4, 5].map((page) => ({ version: 1, page }))));
  });

  it("carries on where they left off", async () => {
    stubModule({ ...INDUCTION, resume_at: 3 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    expect(await screen.findByLabelText("Page 4 of 5")).toBeInTheDocument();
    expect(screen.getByLabelText("Lifting safely")).toBeInTheDocument();
  });

  it("keeps a playing video's learner signed in, however long nobody taps", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const calls = stubModule({ ...INDUCTION, resume_at: 3 });
      renderApp(KIM, Date.now(), "/module/site-induction");
      const video = await screen.findByLabelText("Lifting safely");
      // twenty minutes of a video playing, and not a tap
      for (let minute = 0; minute < 20; minute++) {
        await act(async () => { vi.advanceTimersByTime(60_000); });
        fireEvent.timeUpdate(video);
      }
      expect(screen.getByLabelText("Lifting safely")).toBeInTheDocument();
      expect(calls.filter((c) => c.url === "/v1/auth/me").length).toBeGreaterThanOrEqual(15);
      // once it stops, the idle time runs again
      await act(async () => { vi.advanceTimersByTime(16 * 60_000); });
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says so when a video can't be played", async () => {
    stubModule({ ...INDUCTION, resume_at: 3 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    fireEvent.error(await screen.findByLabelText("Lifting safely"));
    expect(screen.getByRole("alert")).toHaveTextContent("The video couldn't be played.");
  });

  it("keeps focus with the reader: each new page's heading takes it", async () => {
    stubModule();
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "The yard" }));
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Welcome" }));
  });

  it("takes focus to the quiz from the last page", async () => {
    stubModule({ ...INDUCTION, resume_at: 4 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByRole("button", { name: "Start the quiz" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "The quiz" }));
  });

  it("saves only the last page tapped when taps outrun the saves", async () => {
    const held: Array<() => void> = [];
    const calls = stubApi(((method: string, url: string) => {
      if (url === "/v1/modules/site-induction") return json(200, INDUCTION);
      if (method === "PUT") return new Promise<Response>((done) => held.push(() => done(new Response(null, { status: 204 }))));
      return null;
    }) as unknown as Parameters<typeof stubApi>[0]);
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("Page 4 of 5")).toBeInTheDocument();
    // one save at a time: the rest wait for it
    expect(places(calls)).toEqual([{ version: 1, page: 1 }]);
    await act(async () => { held.shift()!(); });
    await waitFor(() => expect(places(calls)).toEqual([{ version: 1, page: 1 }, { version: 1, page: 3 }]));
    await act(async () => { held.shift()!(); });
    expect(places(calls).at(-1)).toEqual({ version: 1, page: 3 });
    expect(held).toHaveLength(0);
  });

  it("offers to load a picture again when its link has run out", async () => {
    let n = 0;
    const calls = stubApi((_m, url) => url === "/v1/modules/site-induction"
      ? json(200, { ...INDUCTION, resume_at: 0, version: { ...INDUCTION.version, pages: INDUCTION.version.pages.map((p) =>
          p.file ? { ...p, file: { ...p.file, link: `${p.file.link}&n=${n++}` } } : p) } })
      : method204(_m));
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByRole("button", { name: "Next" }));
    const first = screen.getByRole("img", { name: "The yard" }).getAttribute("src");
    fireEvent.error(screen.getByRole("img", { name: "The yard" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The picture couldn't be shown.");
    expect(screen.queryByRole("img", { name: "The yard" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load it again" }));
    const again = await screen.findByRole("img", { name: "The yard" });
    expect(again.getAttribute("src")).not.toBe(first);
    // still on the same page
    expect(screen.getByLabelText("Page 2 of 5")).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/v1/modules/site-induction")).toHaveLength(2);
  });

  it("says when there is nothing to take yet", async () => {
    stubApi((_m, url) => url === "/v1/modules/site-induction"
      ? json(404, { detail: "Site induction has nothing to take yet" }) : null);
    renderApp(KIM, Date.now(), "/module/site-induction");
    expect(await screen.findByRole("alert")).toHaveTextContent("There's nothing to do here yet. Ask your manager.");
  });

  it("hands in the answers and says Ding! on a pass", async () => {
    const calls = stubModule({ ...INDUCTION, resume_at: 5 });
    renderApp(KIM, Date.now(), "/module/site-induction");
    const handIn = await screen.findByRole("button", { name: "Hand it in" });
    expect(screen.getByText("2 questions. You need 80% to pass, and you can try again.")).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("group", { name: "1. Where do you sign in?" })).getByLabelText("The gatehouse"));
    expect(handIn).toBeDisabled();
    await userEvent.click(within(screen.getByRole("group", { name: "2. What do you wear on the floor?" })).getByLabelText("Your PPE"));
    await userEvent.click(handIn);
    const passed = await screen.findByRole("status", { name: "Passed" });
    expect(passed).toHaveTextContent("Ding!You passed Site induction with 100%.");
    // the form went: focus goes to the result, so it is read out
    expect(document.activeElement).toBe(passed);
    expect(calls.find((c) => c.url === "/v1/modules/site-induction/attempts")?.body).toEqual({ version: 1, answers: [0, 1] });
  });

  it("gives the score after a fail, then another go", async () => {
    const calls = stubModule({ ...INDUCTION, resume_at: 5 }, [json(201, FAIL), json(201, PASS)]);
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByLabelText("The canteen"));
    await userEvent.click(screen.getByLabelText("Your PPE"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    const missed = await screen.findByRole("status", { name: "Not passed" });
    expect(missed).toHaveTextContent("50%Not this time: you need 80% to pass. Read it again, or have another go.");
    expect(document.activeElement).toBe(missed);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "The quiz" }));
    // a fresh start: nothing chosen
    expect(screen.getByLabelText("The canteen")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Hand it in" })).toBeDisabled();
    await userEvent.click(screen.getByLabelText("The gatehouse"));
    await userEvent.click(screen.getByLabelText("Your PPE"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    expect(await screen.findByRole("status", { name: "Passed" })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([
      { version: 1, answers: [1, 1] }, { version: 1, answers: [0, 1] }]);
  });

  it("goes back to the pages after a fail", async () => {
    stubModule({ ...INDUCTION, resume_at: 5 }, [json(201, FAIL)]);
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByLabelText("The canteen"));
    await userEvent.click(screen.getByLabelText("Thongs"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    await userEvent.click(await screen.findByRole("button", { name: "Read it again" }));
    expect(screen.getByLabelText("Page 1 of 5")).toBeInTheDocument();
  });

  it("starts the new version when one came out while they read", async () => {
    let module: Module = { ...INDUCTION, resume_at: 5 };
    stubApi((method, url) => {
      if (url === "/v1/modules/site-induction") return json(200, module);
      if (method === "POST" && url === "/v1/modules/site-induction/attempts") {
        module = { ...INDUCTION, version: { ...INDUCTION.version, id: 2, version: 2 } };
        return json(409, { detail: "version 2 is the one to take now: start it", code: "new_version" });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/module/site-induction");
    await userEvent.click(await screen.findByLabelText("The gatehouse"));
    await userEvent.click(screen.getByLabelText("Your PPE"));
    await userEvent.click(screen.getByRole("button", { name: "Hand it in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The module has changed: start the new version.");
    expect(await screen.findByLabelText("Page 1 of 5")).toBeInTheDocument();
  });
});
