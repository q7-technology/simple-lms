import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Me } from "../api/types";
import { json, KIM, listen, renderApp, stubApi } from "./harness";

vi.mock("../lib/picture", () => ({
  toBlob: async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: "image/png" }),
  forSending: async (f: File) => f.type === "application/pdf" ? f : new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: "image/jpeg" }),
}));

/** Sam, a supervisor, on his phone with his PIN. */
const SAM: Me = { ...KIM, id: 2, code: "SV001", name: "Sam Vu", permission: "supervisor",
                  scopes: ["training:read", "training:write", "signoffs:write"] };
const PEOPLE = [{ code: "LL042", name: "Kim Lee", practicals: [
  { key: "forklift-practical", name: "Forklift practical", status: "missing", expires_on: null }] }];
const V1 = { id: 1, version: 1, note: null, items: [
  { id: 11, text: "Checks the forks, chains and tyres" }, { id: 12, text: "Lifts a pallet to the top rack" }] };
const FORKLIFT = { key: "forklift-practical", name: "Forklift practical", version: V1 };
const KIMS = "/signoff/LL042/forklift-practical";

/** The API as Sam sees it; `signoff` answers the sign-off itself. */
function stubSignoff(signoff: (body: unknown) => Response = () => json(201, { kind: "granted" }),
                     practical: () => unknown = () => FORKLIFT) {
  let signatures = 0;
  return stubApi((method, url, body) => {
    if (url === "/v1/people/SV001/training") return json(200, { person: { code: "SV001", name: "Sam Vu" }, today: "2026-10-12", items: [] });
    if (url === "/v1/signoffs/people") return json(200, PEOPLE);
    if (url === "/v1/practicals/forklift-practical") return json(200, practical());
    if (method === "POST" && url === "/v1/uploads?purpose=signature") return json(201, { id: `sig-${++signatures}` });
    if (method === "POST" && url === "/v1/uploads?purpose=signoff-photo") return json(201, { id: "photo-1" });
    if (method === "POST" && url === "/v1/people/LL042/signoffs") return signoff(body);
    return null;
  });
}

/** jsdom draws nothing, so the pads get a context that takes the strokes. */
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

/** Sam ticks everything and signs, and hands the phone to Kim. */
async function samTicksAndSigns() {
  for (const item of V1.items) await userEvent.click(await screen.findByLabelText(item.text));
  signWithAFinger();
  await userEvent.click(screen.getByRole("button", { name: "Hand the phone to Kim Lee" }));
  return screen.findByRole("heading", { name: "Kim Lee, check and sign" });
}

describe("signing off a practical", () => {
  beforeEach(() => {
    canDraw();
    URL.createObjectURL = vi.fn(() => "blob:photo");
    URL.revokeObjectURL = vi.fn();
  });

  it("Sam ticks every item and signs; Kim checks, signs and types her PIN; Ding!", async () => {
    const heard = listen();
    const calls = stubSignoff();
    renderApp(SAM);
    await userEvent.click(await screen.findByRole("link", { name: "Sign someone off" }));
    const kim = await screen.findByRole("region", { name: "Kim Lee" });
    const link = within(kim).getByRole("link", { name: "Sign off Kim Lee: Forklift practical" });
    expect(link).toHaveTextContent("Forklift practical · Not done yet");
    await userEvent.click(link);
    expect(await screen.findByRole("heading", { name: "Forklift practical" })).toBeInTheDocument();
    const handOver = screen.getByRole("button", { name: "Hand the phone to Kim Lee" });
    await userEvent.click(screen.getByLabelText("Checks the forks, chains and tyres"));
    signWithAFinger();
    // every item, and Sam's signature, before Kim has the phone
    expect(screen.getByText("1 of 2 ticked")).toBeInTheDocument();
    expect(handOver).toBeDisabled();
    await userEvent.click(screen.getByLabelText("Lifts a pallet to the top rack"));
    await userEvent.type(screen.getByLabelText("A note (optional)"), "Smooth on the ramp");
    await userEvent.upload(screen.getByLabelText(/A photo/), new File(["x"], "yard.jpg", { type: "image/jpeg" }));
    await userEvent.click(handOver);

    expect(await screen.findByRole("heading", { name: "Kim Lee, check and sign" })).toBeInTheDocument();
    // Kim holds the phone: nothing leads to Sam's training from here
    expect(screen.queryByRole("link", { name: "Back to My training" })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "What was ticked" })).toHaveTextContent("Lifts a pallet to the top rack");
    expect(screen.getByText("Their note: “Smooth on the ramp”")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm" });
    await userEvent.type(screen.getByLabelText("Your PIN"), "2468");
    expect(confirm).toBeDisabled();
    signWithAFinger();
    await userEvent.click(confirm);
    expect(await screen.findByRole("status", { name: "Signed off" })).toHaveTextContent("Kim Lee is signed off for Forklift practical.");
    // out loud too, as a pass does, woken by the tap on Confirm
    expect(heard).toEqual({ notes: 2, woken: 1 });
    expect(calls.filter((c) => c.url.startsWith("/v1/uploads")).map((c) => [c.url, c.contentType])).toEqual([
      ["/v1/uploads?purpose=signature", "image/png"], ["/v1/uploads?purpose=signoff-photo", "image/jpeg"],
      ["/v1/uploads?purpose=signature", "image/png"]]);
    expect(calls.find((c) => c.url === "/v1/people/LL042/signoffs")?.body).toEqual({
      competency: "forklift-practical", version: 1, ticked: [11, 12], note: "Smooth on the ramp", photo: "photo-1",
      supervisor_signature: "sig-1", learner_signature: "sig-2", learner_pin: "2468" });
  });

  it("says a wrong PIN, keeps none of it, and lets Kim try again", async () => {
    let tries = 0;
    const calls = stubSignoff(() => ++tries === 1
      ? json(422, { errors: [{ field: "learner_pin", message: "that isn't Kim Lee's PIN: try again" }] })
      : json(201, { kind: "granted" }));
    renderApp(SAM, Date.now(), KIMS);
    await samTicksAndSigns();
    signWithAFinger();
    await userEvent.type(screen.getByLabelText("Your PIN"), "1357");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That isn't Kim Lee's PIN: try again.");
    expect(screen.getByLabelText("Your PIN")).toHaveValue("");
    await userEvent.type(screen.getByLabelText("Your PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("status", { name: "Signed off" })).toBeInTheDocument();
    const sent = calls.filter((c) => c.url === "/v1/people/LL042/signoffs").map((c) => (c.body as { learner_pin: string }).learner_pin);
    expect(sent).toEqual(["1357", "2468"]);
    expect(screen.queryByLabelText("Your PIN")).not.toBeInTheDocument();
  });

  it("goes back to Sam when the checklist changed meanwhile", async () => {
    let practical: unknown = FORKLIFT;
    stubSignoff(() => {
      practical = { ...FORKLIFT, version: { ...V1, id: 2, version: 2, items: [...V1.items, { id: 13, text: "Parks with the forks down" }] } };
      return json(409, { detail: "version 2 is the checklist now: tick it again", code: "new_version" });
    }, () => practical);
    renderApp(SAM, Date.now(), KIMS);
    await samTicksAndSigns();
    signWithAFinger();
    await userEvent.type(screen.getByLabelText("Your PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The checklist has changed: tick it again, then sign.");
    expect(await screen.findByRole("group", { name: "Checklist, version 2" })).toBeInTheDocument();
    expect(screen.getByLabelText("Parks with the forks down")).not.toBeChecked();
    expect(screen.getByLabelText("Lifts a pallet to the top rack")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Hand the phone to Kim Lee" })).toBeDisabled();
  });

  it("gives the phone back to Sam, ticks kept and his signature to do again", async () => {
    stubSignoff();
    renderApp(SAM, Date.now(), KIMS);
    await samTicksAndSigns();
    await userEvent.click(screen.getByRole("button", { name: "Give it back to Sam Vu" }));
    expect(await screen.findByLabelText("Lifts a pallet to the top rack")).toBeChecked();
    expect(screen.getByRole("img", { name: "Signature pad: empty" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hand the phone to Kim Lee" })).toBeDisabled();
  });

  it("takes a photo, not a PDF", async () => {
    stubSignoff();
    renderApp(SAM, Date.now(), KIMS);
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(await screen.findByLabelText(/A photo/), new File(["%PDF-"], "card.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a photo, not a PDF.");
  });

  it("says when it can't: someone not on the team, or no checklist yet", async () => {
    stubSignoff(undefined, () => null);
    const { unmount } = renderApp(SAM, Date.now(), "/signoff/LL099/forklift-practical");
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't sign this person off: they aren't on your team.");
    unmount();
    stubApi((_m, url) => url === "/v1/signoffs/people" ? json(200, PEOPLE)
      : url === "/v1/practicals/forklift-practical" ? json(404, { detail: "Forklift practical has no checklist yet" }) : null);
    renderApp(SAM, Date.now(), KIMS);
    expect(await screen.findByRole("alert")).toHaveTextContent("There's no checklist for this practical yet. Ask your manager.");
  });

  it("finds a person in a long list", async () => {
    const many = ["Ana Bell", "Bo Chan", "Cy Dunn", "Di Ezra", "Ed Fox", "Flo Gray", "Kim Lee"].map((name, n) => ({
      code: `LL${n}`, name, practicals: [] }));
    stubApi((_m, url) => url === "/v1/signoffs/people" ? json(200, many) : null);
    renderApp(SAM, Date.now(), "/signoff");
    await userEvent.type(await screen.findByLabelText("Find a person"), "kim");
    await waitFor(() => expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(["Kim Lee"]));
    expect(screen.getByText("Not asked for any practical.")).toBeInTheDocument();
  });
});
