import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Checklist, Competency } from "../api/types";
import { setGamePrefs } from "../lib/gamePrefs";
import { json, renderApp, stubApi } from "./harness";

const FORKLIFT: Competency = { id: 5, key: "forklift-practical", name: "Forklift practical", kind: "practical", refresher_months: 12, card_expires: null, active: true };
const V1: Checklist = {
  id: 1, version: 1, note: null, published_by: { code: "MG001", name: "Mel Grant" }, created_at: "2026-09-01T01:00:00Z",
  items: [{ id: 11, text: "Checks the forks, chains and tyres" }, { id: 12, text: "Lifts a pallet to the top rack" }],
};
const PATH = "/v1/practicals/forklift-practical/versions";

/** Competencies with the forklift practical, whose checklists are `versions`; publishing adds the next. */
function stubChecklist(versions: Checklist[], practical = FORKLIFT) {
  let list = versions;
  return stubApi((method, url, body) => {
    if (url === "/v1/competencies") return json(200, { items: [practical], total: 1 });
    if (url === PATH && method === "POST") {
      const { items, note } = body as { items: string[]; note: string | null };
      list = [{ ...V1, id: list.length + 1, version: list.length + 1, note,
                items: items.map((text, n) => ({ id: 20 + n, text })) }, ...list];
      return json(201, list[0]);
    }
    if (url === PATH) return json(200, list);
    return null;
  });
}

async function openForklift() {
  renderApp("/competencies");
  await userEvent.click(await screen.findByRole("button", { name: /Forklift practical/ }));
  return screen.findByRole("dialog", { name: "Forklift practical" });
}

describe("a practical's checklist", () => {
  it("shows the one supervisors tick, and publishes the next as a changed copy", async () => {
    const { calls } = stubChecklist([V1]);
    const drawer = await openForklift();
    expect(await within(drawer).findByText(/is the one supervisors tick/)).toHaveTextContent(
      "Version 1 is the one supervisors tick · published 1 Sep 2026 by Mel Grant");
    const next = within(drawer).getByRole("form", { name: "Version 2" });
    expect(within(next).getByLabelText("Item 1")).toHaveValue("Checks the forks, chains and tyres");
    // a copy as it is would be the same checklist again
    expect(within(next).getByRole("button", { name: "Publish version 2" })).toBeDisabled();
    await userEvent.click(within(next).getByRole("button", { name: "Add an item" }));
    await userEvent.type(within(next).getByLabelText("Item 3"), "Parks with the forks down");
    await userEvent.click(within(next).getByRole("button", { name: "Move item 3 up" }));
    await userEvent.type(within(next).getByLabelText("What changed (optional)"), "parking");
    await userEvent.click(within(next).getByRole("button", { name: "Publish version 2" }));
    // it can't be undone: ask once first
    expect(within(next).getByText("Publish version 2? Its items are frozen once it is, and every sign-off from now on ticks them.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(next).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      items: ["Checks the forks, chains and tyres", "Parks with the forks down", "Lifts a pallet to the top rack"],
      note: "parking" }));
    expect(await within(drawer).findByText(/Version 2/, { selector: "b" })).toBeInTheDocument();
    expect(within(drawer).getByRole("form", { name: "Version 3" })).toBeInTheDocument();
  });

  it("writes version 1 from nothing, and asks before closing on it", async () => {
    const { calls } = stubChecklist([]);
    const drawer = await openForklift();
    expect(await within(drawer).findByText("No checklist yet: nobody can be signed off until there is one.")).toBeInTheDocument();
    const next = within(drawer).getByRole("form", { name: "Version 1" });
    const publish = within(next).getByRole("button", { name: "Publish version 1" });
    expect(publish).toBeDisabled();
    await userEvent.type(within(next).getByLabelText("Item 1"), "Lifts a pallet");
    await userEvent.click(within(next).getByRole("button", { name: "Add an item" }));
    // an empty item is not something to tick
    expect(publish).toBeDisabled();
    await userEvent.click(within(next).getByRole("button", { name: "Remove item 2" }));
    await userEvent.click(within(drawer).getByRole("button", { name: "Close" }));
    expect(within(drawer).getByText("Version 1 has changes that aren't published. Close it anyway?")).toBeInTheDocument();
    await userEvent.click(within(drawer).getByRole("button", { name: "Keep editing" }));
    await userEvent.click(publish);
    await userEvent.click(within(next).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ items: ["Lifts a pallet"], note: null }));
  });

  it("asks for a deactivated practical to be reactivated before a new checklist, with Game Mode off too", async () => {
    // the plain desktop: Competencies is a page of its own, not a drawer over the classroom
    setGamePrefs({ classroom: false });
    stubChecklist([V1], { ...FORKLIFT, active: false });
    const drawer = await openForklift();
    expect(screen.queryByRole("region", { name: "Competencies" })).not.toBeInTheDocument();
    expect(await within(drawer).findByText("Reactivate it to publish a new checklist.")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: /Publish version/ })).not.toBeInTheDocument();
  });
});
