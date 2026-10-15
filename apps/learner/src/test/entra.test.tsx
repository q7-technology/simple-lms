import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { browser } from "../auth/Session";
import { json, KIM, renderApp, stubApi } from "./harness";

const TRAINING = { person: { code: "LL042", name: "Kim Lee" }, today: "2026-10-12", items: [] };
const ALL_ON = { pin: true, password: true, entra: true };
const MICROSOFT = "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize?prompt=login";

describe("signing in to the learner app with Microsoft", () => {
  afterEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); vi.restoreAllMocks(); });

  it("sends the person to Microsoft, keeping a secret in the tab", async () => {
    const go = vi.spyOn(browser, "go").mockImplementation(() => undefined);
    const calls = stubApi((_m, url) => {
      if (url === "/v1/auth/methods") return json(200, ALL_ON);
      if (url === "/v1/auth/entra/start") return json(200, { url: MICROSOFT });
      return null;
    });
    renderApp(null, Date.now(), "/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with Microsoft" }));
    await waitFor(() => expect(go).toHaveBeenCalledWith(MICROSOFT));
    const sent = calls.find((c) => c.url === "/v1/auth/entra/start")?.body as { app: string; verifier: string };
    expect(sent.app).toBe("learner");
    expect(window.sessionStorage.getItem("lms.learner.entra")).toBe(sent.verifier);
  });

  it("finishes when Microsoft sends them back, and shows My training", async () => {
    window.sessionStorage.setItem("lms.learner.entra", "the-tabs-secret");
    const calls = stubApi((_m, url) => {
      if (url === "/v1/auth/entra/finish") return json(200, { token: "lms_s.kim", person: { ...KIM, method: "entra", idle_seconds: 43200 } });
      if (url === "/v1/people/LL042/training") return json(200, TRAINING);
      return null;
    });
    renderApp(null, Date.now(), "/sign-in#entra=the-hand-off");
    expect(await screen.findByRole("heading", { name: "My training" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/v1/auth/entra/finish").map((c) => c.body)).toEqual([
      { code: "the-hand-off", verifier: "the-tabs-secret" }]);
    expect(JSON.parse(window.localStorage.getItem("lms.learner.session")!).person.method).toBe("entra");
  });

  it("says plainly when nobody has that Microsoft account", async () => {
    stubApi((_m, url) => url === "/v1/auth/methods" ? json(200, ALL_ON) : null);
    renderApp(null, Date.now(), "/sign-in#entra_error=not_matched");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nobody in Simple LMS has that Microsoft account. Ask your manager to add you.");
  });

  it("says so when the hand-off has expired, without signing anyone out", async () => {
    stubApi((_m, url) => url === "/v1/auth/entra/finish"
      ? json(401, { detail: "that Microsoft sign-in has finished or expired; try again" }) : null);
    renderApp(null, Date.now(), "/sign-in#entra=too-late");
    expect(await screen.findByRole("alert")).toHaveTextContent("That Microsoft sign-in has finished or expired. Try again.");
  });

  it("offers only the ways that are on", async () => {
    stubApi((_m, url) => url === "/v1/auth/methods" ? json(200, { pin: false, password: true, entra: true }) : null);
    renderApp(null, Date.now(), "/sign-in");
    expect(await screen.findByLabelText("Email")).toBeInTheDocument();
    expect(screen.queryByLabelText("Your code")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in with your code and PIN" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in with Microsoft" })).toBeInTheDocument();
  });

  it("offers Microsoft alone when it is the only way on", async () => {
    stubApi((_m, url) => url === "/v1/auth/methods" ? json(200, { pin: false, password: false, entra: true }) : null);
    renderApp(null, Date.now(), "/sign-in");
    expect(await screen.findByRole("button", { name: "Sign in with Microsoft" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("says when PINs have been switched off", async () => {
    stubApi((_m, url) => url === "/v1/auth/pin-login"
      ? json(403, { detail: "Signing in with a code and PIN is switched off here.", code: "method_off" }) : null);
    renderApp(null, Date.now(), "/sign-in");
    await userEvent.type(await screen.findByLabelText("Your code"), "LL042");
    await userEvent.type(screen.getByLabelText("PIN"), "2468");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Signing in with a code and PIN is switched off here\.$/);
  });
});
