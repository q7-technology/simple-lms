import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Ticket } from "../api/types";
import { MEL, json, renderApp, stubApi } from "./harness";

const KIMS: Ticket = {
  id: 7, person: { code: "LL042", name: "Kim Lee" },
  competency: { key: "forklift-licence", name: "Forklift licence", kind: "ticket" },
  number: "LF0012345", expires_on: "2031-03-01", front: "f-1", back: "b-1", status: "pending",
  reason: null, decided_by: null, decided_at: null, created_at: "2026-10-12T01:00:00Z",
};

function photos(url: string) {
  if (url.startsWith("/v1/uploads/")) {
    return new Response(new Uint8Array([0xff, 0xd8, 0xff]), { status: 200, headers: { "Content-Type": "image/jpeg" } });
  }
  return null;
}

describe("the inbox", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:photo");
    URL.revokeObjectURL = vi.fn();
  });

  it("lists the tickets waiting and shows one's photos", async () => {
    stubApi((_m, url) => url === "/v1/tickets" ? json(200, [KIMS]) : photos(url));
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence: Kim Lee" });
    expect(within(drawer).getByText("LF0012345")).toBeInTheDocument();
    expect(within(drawer).getByText("1 Mar 2031")).toBeInTheDocument();
    expect(await within(drawer).findByRole("img", { name: "The front" })).toHaveAttribute("src", "blob:photo");
    expect(within(drawer).getByRole("img", { name: "The back" })).toBeInTheDocument();
  });

  it("opens a ticket with focus on the drawer, not on Approve", async () => {
    stubApi((_m, url) => url === "/v1/tickets" ? json(200, [KIMS]) : photos(url));
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    const drawer = await screen.findByRole("dialog", { name: "Forklift licence: Kim Lee" });
    expect(drawer).toHaveFocus();
    expect(within(drawer).getByRole("button", { name: "Approve" })).not.toHaveFocus();
  });

  it("approves one, and it leaves the inbox", async () => {
    let waiting = [KIMS];
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/tickets") return json(200, waiting);
      if (method === "POST" && url === "/v1/tickets/7/approve") { waiting = []; return json(200, { ...KIMS, status: "approved" }); }
      return photos(url);
    });
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/Nothing waiting/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/v1/tickets/7/approve")).toBe(true);
  });

  it("sends one back with a reason", async () => {
    let waiting = [KIMS];
    const { calls } = stubApi((method, url) => {
      if (url === "/v1/tickets") return json(200, waiting);
      if (method === "POST" && url === "/v1/tickets/7/reject") { waiting = []; return json(200, { ...KIMS, status: "rejected" }); }
      return photos(url);
    });
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByRole("button", { name: "Reject" })).toBeDisabled();
    await userEvent.type(within(drawer).getByLabelText("Reason (they see this)"), "The photo is blurry");
    await userEvent.click(within(drawer).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/v1/tickets/7/reject")?.body).toEqual({ reason: "The photo is blurry" }));
  });

  it("says so when another manager got there first, and it leaves the inbox", async () => {
    let waiting = [KIMS];
    stubApi((method, url) => {
      if (url === "/v1/tickets") return json(200, waiting);
      if (method === "POST" && url === "/v1/tickets/7/approve") {
        waiting = [];
        return json(409, { detail: "this ticket was approved already", code: "decided" });
      }
      return photos(url);
    });
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Another manager got there first: this ticket was approved already.")).toBeInTheDocument();
    expect(await screen.findByText(/Nothing waiting/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("doesn't end with two full stops when the reason has one", async () => {
    stubApi((method, url) => {
      if (url === "/v1/tickets") return json(200, [KIMS]);
      if (method === "POST" && url === "/v1/tickets/7/approve") {
        return json(409, { detail: "This ticket was approved already.", code: "decided" });
      }
      return photos(url);
    });
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Kim Lee/ }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Another manager got there first: This ticket was approved already.")).toBeInTheDocument();
  });

  it("doesn't offer a manager their own", async () => {
    const own = { ...KIMS, person: { code: MEL.code, name: MEL.name } };
    stubApi((_m, url) => url === "/v1/tickets" ? json(200, [own]) : photos(url));
    renderApp("/inbox");
    await userEvent.click(await screen.findByRole("button", { name: /Mel Grant/ }));
    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Nobody verifies their own ticket: ask another manager.")).toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("is a tab for those who check tickets only", async () => {
    stubApi((_m, url) => url.startsWith("/v1/matrix") ? json(200, { today: "2026-10-12", competencies: [], people: [] })
      : url === "/v1/roles" ? json(200, { items: [], total: 0 }) : null,
    { ...MEL, permission: "supervisor", scopes: ["training:read", "training:write", "matrix:read", "roles:read", "competencies:read"] });
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Matrix" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inbox" })).not.toBeInTheDocument();
  });
});
