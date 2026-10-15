import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Competency, ModuleVersion } from "../api/types";
import { json, renderApp, stubApi, type Call } from "./harness";

const INDUCTION: Competency = { id: 1, key: "site-induction", name: "Site induction", kind: "module", refresher_months: 24, card_expires: true, active: true };
const MEL = { code: "MG001", name: "Mel Grant" };
const EMPTY: ModuleVersion = { id: 1, version: 1, pass_mark: 80, published_at: null, published_by: null, pages: [], questions: [], created_at: "2026-10-12T01:00:00Z" };
const V1: ModuleVersion = {
  ...EMPTY, published_at: "2026-10-12T02:00:00Z", published_by: MEL,
  pages: [
    { kind: "text", title: "Welcome", body: "Sign in at the gatehouse.", url: null, file: null },
    { kind: "video", title: "Lifting safely", body: null, url: null,
      file: { id: "v-1", content_type: "video/mp4", size_bytes: 12_300_000, link: "/v1/media/v-1?session=1&expires=1&sig=x" } },
    { kind: "link", title: "SafeWork", body: null, url: "https://www.safework.nsw.gov.au", file: null },
  ],
  questions: [{ prompt: "Where do you sign in?", options: ["The gatehouse", "The canteen"], correct: 0 }],
};

/** Competencies with the site induction, whose versions are `versions`;
 * starting a draft adds `draft`, and publishing publishes it. */
function stubModule(versions: ModuleVersion[], draft: ModuleVersion = EMPTY) {
  let list = versions;
  return stubApi((method, url, body) => {
    if (url === "/v1/competencies") return json(200, { items: [INDUCTION], total: 1 });
    if (url === "/v1/modules/site-induction/versions") return json(200, list);
    if (method === "POST" && url === "/v1/modules/site-induction/draft") { list = [draft, ...list]; return json(201, draft); }
    if (method === "PUT" && url === "/v1/modules/site-induction/draft") return json(200, { ...list[0], ...(body as object) });
    if (method === "POST" && url === "/v1/modules/site-induction/draft/publish") {
      list = [{ ...list[0], published_at: "2026-10-12T03:00:00Z", published_by: MEL }, ...list.slice(1)];
      return json(200, list[0]);
    }
    if (method === "POST" && url.startsWith("/v1/uploads?purpose=")) {
      return json(201, { id: "u-1", purpose: url.split("=")[1], content_type: "video/mp4", size_bytes: 4_200_000, created_at: "2026-10-12T01:00:00Z" });
    }
    return null;
  });
}

async function openInduction() {
  renderApp("/competencies");
  await userEvent.click(await screen.findByRole("button", { name: /Site induction/ }));
  return screen.findByRole("dialog", { name: "Site induction" });
}

const put = (calls: Call[]) => calls.find((c) => c.method === "PUT")?.body;

async function addPage(drawer: HTMLElement, kind: string) {
  await userEvent.selectOptions(within(drawer).getByLabelText("New page"), kind);
  await userEvent.click(within(drawer).getByRole("button", { name: "Add a page" }));
}

describe("a module's pages and quiz", () => {
  it("starts version 1 and saves its pages, its questions and its pass mark", async () => {
    const { calls } = stubModule([]);
    const drawer = await openInduction();
    expect(await within(drawer).findByText(/Nothing published yet/)).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Start version 1" }));
    expect(await within(drawer).findByText(/Version 1 is a draft/)).toBeInTheDocument();

    await addPage(drawer, "Text");
    const one = within(drawer).getByRole("group", { name: "Page 1" });
    await userEvent.type(within(one).getByLabelText("Title"), "Welcome");
    await userEvent.type(within(one).getByLabelText("Text"), "Sign in at the gatehouse.");
    await addPage(drawer, "Link");
    const two = within(drawer).getByRole("group", { name: "Page 2" });
    await userEvent.type(within(two).getByLabelText("Title"), "SafeWork");
    await userEvent.type(within(two).getByLabelText("Web address"), "https://www.safework.nsw.gov.au");

    await userEvent.click(within(drawer).getByRole("button", { name: "Add a question" }));
    const q = within(drawer).getByRole("group", { name: "Question 1" });
    await userEvent.type(within(q).getByLabelText("Question"), "Where do you sign in?");
    await userEvent.click(within(q).getByRole("button", { name: "Add an answer" }));
    await userEvent.type(within(q).getByLabelText("Answer 1"), "The canteen");
    await userEvent.type(within(q).getByLabelText("Answer 2"), "The gatehouse");
    await userEvent.type(within(q).getByLabelText("Answer 3"), "Anywhere");
    await userEvent.click(within(q).getByLabelText("Answer 2 is the right one"));
    await userEvent.click(within(q).getByRole("button", { name: "Remove answer 3" }));
    const mark = within(drawer).getByLabelText("Pass mark (%)");
    await userEvent.clear(mark);
    await userEvent.type(mark, "70");

    await userEvent.click(within(drawer).getByRole("button", { name: "Save draft" }));
    expect(await within(drawer).findByText("Draft saved.")).toBeInTheDocument();
    expect(put(calls)).toEqual({
      pass_mark: 70,
      pages: [
        { kind: "text", title: "Welcome", body: "Sign in at the gatehouse." },
        { kind: "link", title: "SafeWork", url: "https://www.safework.nsw.gov.au", body: null },
      ],
      questions: [{ prompt: "Where do you sign in?", options: ["The canteen", "The gatehouse"], correct: 1 }],
    });
  });

  it("sends a page's video as it is, then names it on the page", async () => {
    const { calls } = stubModule([EMPTY]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 1 is a draft/);
    await addPage(drawer, "Video");
    const page = within(drawer).getByRole("group", { name: "Page 1" });
    await userEvent.type(within(page).getByLabelText("Title"), "Lifting safely");
    const video = new File([new Uint8Array([0, 0, 0, 0x18])], "lifting.mp4", { type: "video/mp4" });
    await userEvent.upload(within(page).getByLabelText("File"), video);
    expect(await within(page).findByText("MP4 · 4.2 MB")).toBeInTheDocument();
    const sent = calls.find((c) => c.url === "/v1/uploads?purpose=page-video")!;
    expect(sent.body).toBe(video);
    expect(sent.contentType).toBe("video/mp4");
    await userEvent.click(within(drawer).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(put(calls)).toMatchObject({
      pages: [{ kind: "video", title: "Lifting safely", file: "u-1", body: null }] }));
  });

  it("won't send a video over 200 MB", async () => {
    const { calls } = stubModule([EMPTY]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 1 is a draft/);
    await addPage(drawer, "Video");
    const huge = new File([new Uint8Array([0])], "long.mp4", { type: "video/mp4" });
    Object.defineProperty(huge, "size", { value: 200_000_001 });
    await userEvent.upload(within(drawer).getByLabelText("File"), huge);
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("That file is too big: the most is 200 MB.");
    expect(calls.some((c) => c.url.startsWith("/v1/uploads"))).toBe(false);
  });

  it("won't send a picture over 20 MB", async () => {
    const { calls } = stubModule([EMPTY]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 1 is a draft/);
    await addPage(drawer, "Picture");
    const big = new File([new Uint8Array([0xff, 0xd8])], "site.jpg", { type: "image/jpeg" });
    Object.defineProperty(big, "size", { value: 20_000_001 });
    await userEvent.upload(within(drawer).getByLabelText("File"), big);
    expect(await within(drawer).findByRole("alert")).toHaveTextContent("That file is too big: the most is 20 MB.");
    expect(calls.some((c) => c.url.startsWith("/v1/uploads"))).toBe(false);
  });

  it("moves and removes pages before it is saved", async () => {
    const { calls } = stubModule([{ ...V1, published_at: null, published_by: null, version: 2, id: 2 }]);
    const drawer = await openInduction();
    await within(drawer).findByText(/Version 2 is a draft/);
    await userEvent.click(within(drawer).getByRole("button", { name: "Move page 3 up" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Remove page 1" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect((put(calls) as { pages: { title: string }[] }).pages.map((p) => p.title))
      .toEqual(["SafeWork", "Lifting safely"]));
    expect((put(calls) as { pages: unknown[] }).pages[1]).toEqual({ kind: "video", title: "Lifting safely", file: "v-1", body: null });
  });

  it("asks before publishing, since publishing freezes it", async () => {
    const { calls } = stubModule([{ ...V1, published_at: null, published_by: null }]);
    const drawer = await openInduction();
    await userEvent.click(await within(drawer).findByRole("button", { name: "Publish version 1" }));
    expect(within(drawer).getByText("Publish version 1? Its pages and questions are frozen once it is, and everyone takes it from now.")).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Cancel" }));
    expect(calls.some((c) => c.method !== "GET")).toBe(false);

    await userEvent.click(within(drawer).getByRole("button", { name: "Publish version 1" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Publish" }));
    // saved as it is on the screen, then published
    await waitFor(() => expect(calls.filter((c) => c.method !== "GET").map((c) => `${c.method} ${c.url}`)).toEqual([
      "PUT /v1/modules/site-induction/draft", "POST /v1/modules/site-induction/draft/publish"]));
    expect(await within(drawer).findByText(/is the one people take/)).toHaveTextContent(
      "Version 1 is the one people take · published 12 Oct 2026 by Mel Grant · 3 pages · 1 question · pass mark 80%");
    expect(within(drawer).getByRole("button", { name: "Start version 2" })).toBeInTheDocument();
  });

  it("can't publish a draft without a page and a question", async () => {
    stubModule([EMPTY]);
    const drawer = await openInduction();
    expect(await within(drawer).findByRole("button", { name: "Publish version 1" })).toBeDisabled();
    expect(within(drawer).getByText("It needs a page and a question before it can be published.")).toBeInTheDocument();
  });

  it("shows the published version and starts the next as a copy of it", async () => {
    const copy = { ...V1, id: 2, version: 2, published_at: null, published_by: null };
    stubModule([V1], copy);
    const drawer = await openInduction();
    expect(await within(drawer).findByText(/People keep taking version 1 until you publish it/)).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Start version 2" }));
    expect(await within(drawer).findByText(/Version 2 is a draft/)).toBeInTheDocument();
    expect(within(within(drawer).getByRole("group", { name: "Page 1" })).getByLabelText("Title")).toHaveValue("Welcome");
    expect(within(within(drawer).getByRole("group", { name: "Page 2" })).getByText("MP4 · 12.3 MB")).toBeInTheDocument();
  });
});
