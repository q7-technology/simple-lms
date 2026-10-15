import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, KIM, listen, renderApp, stubApi } from "./harness";
import { addInk, ENOUGH_INK } from "../pictures";

vi.mock("../lib/picture", () => ({
  toBlob: async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" }),
  forSending: async (f: Blob) => f,
}));

const TRAINING = {
  person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12",
  items: [{ key: "whs-policy", name: "WHS policy", kind: "policy", status: "missing", granted_on: null,
            expires_on: null, card_expires: null, waiting: false }],
};
const V2: { id: number; version: number; body: string; note: string | null; created_at: string } = { id: 2, version: 2, body: "Wear your PPE, and hi-vis in the yard.", note: "hi-vis in the yard", created_at: "2026-10-01T00:00:00Z" };
const WHS = { key: "whs-policy", name: "WHS policy", version: V2 };

/** jsdom draws nothing, so the pad gets a context that takes the strokes. */
function canDraw() {
  const ctx = { scale() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {} };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
}

function signWithAFinger() {
  const pad = screen.getByRole("img", { name: "Signature pad: empty" });
  fireEvent.pointerDown(pad, { clientX: 10, clientY: 10 });
  fireEvent.pointerMove(pad, { clientX: 60, clientY: 30 });
  fireEvent.pointerUp(pad);
}

describe("signing a policy", () => {
  beforeEach(canDraw);

  it("reads it, takes a typed name and a finger signature, and says Ding!", async () => {
    const calls = stubApi((method, url) => {
      if (url === "/v1/people/LL042/training") return json(200, TRAINING);
      if (url === "/v1/policies/whs-policy") return json(200, WHS);
      if (method === "POST" && url === "/v1/uploads?purpose=signature") return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") return json(201, { kind: "granted" });
      return null;
    });
    renderApp(KIM);
    await userEvent.click(await screen.findByRole("link", { name: "Read and sign: WHS policy" }));
    expect(await screen.findByRole("article", { name: "The policy" })).toHaveTextContent("Wear your PPE, and hi-vis in the yard.");
    expect(screen.getByText(/What changed: hi-vis in the yard/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Sign" });
    await userEvent.type(screen.getByLabelText("Type your name"), "Kim Lee");
    expect(button).toBeDisabled();
    signWithAFinger();
    expect(screen.getByRole("img", { name: "Signature pad: signed" })).toBeInTheDocument();
    await userEvent.click(button);
    expect(await screen.findByRole("status", { name: "Signed" })).toHaveTextContent("Ding!");
    expect(calls.find((c) => c.url === "/v1/uploads?purpose=signature")?.contentType).toBe("image/png");
    expect(calls.find((c) => c.url === "/v1/policies/whs-policy/sign")?.body).toEqual({
      version: 2, signed_name: "Kim Lee", signature: "sig-1" });
  });

  it("says Ding! out loud once it is signed, woken by the tap on Sign", async () => {
    const heard = listen();
    stubApi((method, url) => {
      if (url === "/v1/policies/whs-policy") return json(200, WHS);
      if (method === "POST" && url === "/v1/uploads?purpose=signature") return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") return json(201, { kind: "granted" });
      return null;
    });
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kim Lee");
    signWithAFinger();
    await userEvent.click(screen.getByRole("button", { name: "Sign" }));
    await screen.findByRole("status", { name: "Signed" });
    expect(heard).toEqual({ notes: 2, woken: 1 });
  });

  it("shows the new version when one came out while they read", async () => {
    let policy: typeof WHS = { ...WHS, version: { ...V2, id: 1, version: 1, body: "Wear your PPE on the floor." } };
    stubApi((method, url) => {
      if (url === "/v1/policies/whs-policy") return json(200, policy);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") {
        policy = WHS;
        return json(409, { detail: "version 2 is the one to sign now: read it first", code: "new_version" });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kim Lee");
    signWithAFinger();
    await userEvent.click(screen.getByRole("button", { name: "Sign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The policy has changed: read the new version and sign again.");
    expect(await screen.findByRole("article", { name: "The policy" })).toHaveTextContent("hi-vis in the yard");
    // the ink was for the old text: the pad is empty again and Sign waits for a new signature
    expect(screen.getByRole("img", { name: "Signature pad: empty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();
  });

  it("doesn't take a smudge as a signature", async () => {
    stubApi((_m, url) => url === "/v1/policies/whs-policy" ? json(200, WHS) : null);
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kim Lee");
    const pad = screen.getByRole("img", { name: "Signature pad: empty" });
    fireEvent.pointerDown(pad, { clientX: 10, clientY: 10 });
    fireEvent.pointerMove(pad, { clientX: 14, clientY: 13 });
    fireEvent.pointerUp(pad);
    expect(screen.getByRole("img", { name: "Signature pad: empty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();
  });

  it("clears the pad when the screen turns, and says to sign again", async () => {
    let resized: () => void = () => {};
    vi.stubGlobal("ResizeObserver", class {
      constructor(cb: () => void) { resized = cb; }
      observe() {}
      disconnect() {}
    });
    stubApi((_m, url) => url === "/v1/policies/whs-policy" ? json(200, WHS) : null);
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kim Lee");
    signWithAFinger();
    expect(screen.getByRole("button", { name: "Sign" })).toBeEnabled();
    // the same size again (as when it is first watched) changes nothing
    act(() => resized());
    expect(screen.getByRole("img", { name: "Signature pad: signed" })).toBeInTheDocument();
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(700);
    act(() => resized());
    expect(screen.getByRole("img", { name: "Signature pad: empty" })).toBeInTheDocument();
    expect(screen.getByText("Sign again: the screen turned.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign" })).toBeDisabled();
  });

  it("says whose name to type", async () => {
    stubApi((_m, url) => url === "/v1/policies/whs-policy" ? json(200, WHS) : null);
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    expect(await screen.findByLabelText("Type your name")).toHaveAccessibleDescription(
      "Type your name as it is on your record: Kim Lee");
  });

  it("says what the name needs, and keeps what was typed", async () => {
    stubApi((method, url) => {
      if (url === "/v1/policies/whs-policy") return json(200, WHS);
      if (method === "POST" && url.startsWith("/v1/uploads")) return json(201, { id: "sig-1" });
      if (method === "POST" && url === "/v1/policies/whs-policy/sign") {
        return json(422, { errors: [{ field: "signed_name", message: "type your name as it is on your record: Kim Lee" }] });
      }
      return null;
    });
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    await userEvent.type(await screen.findByLabelText("Type your name"), "Kimberley");
    signWithAFinger();
    await userEvent.click(screen.getByRole("button", { name: "Sign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Type your name as it is on your record: Kim Lee.");
    expect(screen.getByLabelText("Type your name")).toHaveValue("Kimberley");
  });

  it("says plainly when there is nothing to sign yet", async () => {
    stubApi((_m, url) => url === "/v1/policies/whs-policy" ? json(404, { detail: "WHS policy has no version to sign yet" }) : null);
    renderApp(KIM, Date.now(), "/sign/whs-policy");
    expect(await screen.findByRole("alert")).toHaveTextContent("There's nothing to sign here yet. Ask your manager.");
  });
});

describe("how much ink is a signature", () => {
  it("adds up the length of the strokes", () => {
    expect(addInk(0, [0, 0], [3, 4])).toBe(5);
    expect(addInk(5, [3, 4], [6, 8])).toBe(10);
  });

  it("asks for a real stroke, not a dot", () => {
    expect(ENOUGH_INK).toBe(40);
    expect(addInk(0, [0, 0], [30, 0]) >= ENOUGH_INK).toBe(false);
    expect(addInk(30, [30, 0], [40, 0]) >= ENOUGH_INK).toBe(true);
  });
});
