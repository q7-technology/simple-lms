import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, KIM, renderApp, stubApi } from "./harness";

vi.mock("../lib/picture", () => ({
  toBlob: async () => new Blob([new Uint8Array([0x89, 0x50])], { type: "image/png" }),
  // a photo is made small on the phone: here, a JPEG of its own
  forSending: async (f: File) => f.type === "application/pdf" ? f : new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" }),
}));

const ITEM = { key: "forklift-licence", name: "Forklift licence", kind: "ticket", status: "missing", granted_on: null,
               expires_on: null, card_expires: true, waiting: false };
const training = (items: unknown[]) => ({ person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12", items });

describe("adding a ticket", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:photo");
    URL.revokeObjectURL = vi.fn();
  });

  it("sends the photos, the number and the date, and it waits for a check", async () => {
    let uploads = 0;
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url === "/v1/uploads?purpose=ticket") return json(201, { id: `u-${++uploads}` });
      if (method === "POST" && url === "/v1/tickets") return json(201, { id: 7, status: "pending" });
      return null;
    });
    renderApp(KIM);
    await userEvent.click(await screen.findByRole("link", { name: "Add your ticket: Forklift licence" }));
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    expect(await screen.findByRole("img", { name: "Photo of the front" })).toHaveAttribute("src", "blob:photo");
    await user.upload(screen.getByLabelText(/Photo of the back/), new File(["x"], "back.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Number on the card"), "LF0012345");
    const send = screen.getByRole("button", { name: "Send for checking" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("Good until (the date on the card)"), "2031-03-01");
    await user.click(send);
    expect(await screen.findByRole("status", { name: "Sent" })).toHaveTextContent("waits for a manager's check");
    expect(calls.filter((c) => c.url === "/v1/uploads?purpose=ticket").map((c) => c.contentType)).toEqual(["image/jpeg", "image/jpeg"]);
    expect(calls.find((c) => c.url === "/v1/tickets")?.body).toEqual({
      competency: "forklift-licence", number: "LF0012345", expires_on: "2031-03-01", front: "u-1", back: "u-2" });
  });

  it("takes a PDF as it is, and no date for a card that doesn't run out", async () => {
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([{ ...ITEM, key: "white-card", name: "White card", card_expires: false }]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "u-1" });
      if (method === "POST" && url === "/v1/tickets") return json(201, { id: 8 });
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/white-card");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["%PDF-"], "card.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("PDF added · tap to change")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Good until/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Number on the card"), "WC 1234");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/v1/tickets")?.body).toEqual({
      competency: "white-card", number: "WC 1234", expires_on: null, front: "u-1", back: null }));
    expect(calls.find((c) => c.url.startsWith("/v1/uploads"))?.contentType).toBe("application/pdf");
  });

  it("says why the last one was sent back", async () => {
    stubApi((_m, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") {
        return json(200, [{ id: 3, competency: { key: "forklift-licence", name: "Forklift licence", kind: "ticket" }, number: "LF1",
                            expires_on: "2031-03-01", status: "rejected", reason: "The photo is blurry.", created_at: "2026-10-01T00:00:00Z" }]);
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    expect(await screen.findByText("Your last one was sent back: The photo is blurry.")).toBeInTheDocument();
  });

  it("shows a ticket sent in as waiting, with nothing to add", async () => {
    stubApi((_m, url) => url === "/v1/people/LL042/training" ? json(200, training([{ ...ITEM, waiting: true }])) : null);
    renderApp(KIM);
    expect(await screen.findByText("Sent in · waiting for a manager's check")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Add your ticket/ })).not.toBeInTheDocument();
  });

  it("says what the API wants changed", async () => {
    stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "u-1" });
      if (method === "POST" && url === "/v1/tickets") {
        return json(422, { errors: [{ field: "expires_on", message: "this card has run out: send the new one" }] });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Number on the card"), "LF1");
    await user.type(screen.getByLabelText("Good until (the date on the card)"), "2026-10-13");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This card has run out: send the new one.");
  });

  it("sends each photo once, however often the ticket is tried", async () => {
    let uploads = 0;
    let tries = 0;
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url === "/v1/uploads?purpose=ticket") return json(201, { id: `u-${++uploads}` });
      if (method === "POST" && url === "/v1/tickets") {
        return ++tries === 1
          ? json(422, { errors: [{ field: "expires_on", message: "this card has run out: send the new one" }] })
          : json(201, { id: 9, status: "pending" });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    await user.upload(screen.getByLabelText(/Photo of the back/), new File(["x"], "back.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Number on the card"), "LF1");
    const date = screen.getByLabelText("Good until (the date on the card)");
    // the API's day has moved on since the page loaded: it refuses tomorrow
    await user.type(date, "2026-10-13");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This card has run out");
    await user.clear(date);
    await user.type(date, "2031-03-01");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    expect(await screen.findByRole("status", { name: "Sent" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/v1/uploads?purpose=ticket")).toHaveLength(2);
    expect(calls.filter((c) => c.url === "/v1/tickets").map((c) => c.body)).toEqual([
      expect.objectContaining({ expires_on: "2026-10-13", front: "u-1", back: "u-2" }),
      expect.objectContaining({ expires_on: "2031-03-01", front: "u-1", back: "u-2" }),
    ]);
  });

  it("asks for a date after the API's today", async () => {
    stubApi((_m, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    expect(await screen.findByLabelText("Good until (the date on the card)")).toHaveAttribute("min", "2026-10-13");
  });

  it("refuses a PDF over 20 MB before sending it", async () => {
    const calls = stubApi((_m, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    const user = userEvent.setup();
    const big = new File([new Uint8Array(20_000_001)], "card.pdf", { type: "application/pdf" });
    await user.upload(await screen.findByLabelText(/Photo of the front/), big);
    expect(await screen.findByRole("alert")).toHaveTextContent("That file is too big: the most is 20 MB.");
    expect(screen.queryByText("PDF added · tap to change")).not.toBeInTheDocument();
    expect(calls.some((c) => c.url.startsWith("/v1/uploads"))).toBe(false);
  });

  it("takes the back photo away again", async () => {
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "u-1" });
      if (method === "POST" && url === "/v1/tickets") return json(201, { id: 10 });
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    await user.upload(screen.getByLabelText(/Photo of the back/), new File(["x"], "back.jpg", { type: "image/jpeg" }));
    expect(await screen.findByRole("img", { name: "Photo of the back" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove the photo of the front" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove the photo of the back" }));
    expect(screen.queryByRole("img", { name: "Photo of the back" })).not.toBeInTheDocument();
    expect(screen.getByText("If there's anything on the back")).toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo");
    await user.type(screen.getByLabelText("Number on the card"), "LF1");
    await user.type(screen.getByLabelText("Good until (the date on the card)"), "2031-03-01");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    await waitFor(() => expect(calls.find((c) => c.url === "/v1/tickets")?.body).toEqual(expect.objectContaining({ back: null })));
    expect(calls.filter((c) => c.url.startsWith("/v1/uploads"))).toHaveLength(1);
  });

  it("takes one already waiting as sent", async () => {
    stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, training([ITEM]));
      if (url === "/v1/people/LL042/tickets") return json(200, []);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "u-1" });
      if (method === "POST" && url === "/v1/tickets") {
        return json(409, { detail: "your Forklift licence is already waiting for a manager's check", code: "already_waiting" });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/ticket/forklift-licence");
    const user = userEvent.setup();
    await user.upload(await screen.findByLabelText(/Photo of the front/), new File(["x"], "front.jpg", { type: "image/jpeg" }));
    await user.type(screen.getByLabelText("Number on the card"), "LF1");
    await user.type(screen.getByLabelText("Good until (the date on the card)"), "2031-03-01");
    await user.click(screen.getByRole("button", { name: "Send for checking" }));
    expect(await screen.findByRole("status", { name: "Sent" })).toHaveTextContent("waits for a manager's check");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
