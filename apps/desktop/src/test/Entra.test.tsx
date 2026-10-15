import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { browser } from "../auth/AuthContext";
import { json, MEL, renderApp, stubApi } from "./harness";

const EMPTY = { today: "2026-10-12", competencies: [], people: [] };
const ALL_ON = { pin: true, password: true, entra: true };
const MICROSOFT = "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize?state=st";

describe("signing in to the desktop with Microsoft", () => {
  afterEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); vi.restoreAllMocks(); });

  it("sends the person to Microsoft, keeping a secret in the tab", async () => {
    const go = vi.spyOn(browser, "go").mockImplementation(() => undefined);
    const { calls } = stubApi((_method, url) => {
      if (url === "/v1/auth/methods") return json(200, ALL_ON);
      if (url === "/v1/auth/entra/start") return json(200, { url: MICROSOFT });
      return null;
    });
    renderApp("/sign-in", false);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with Microsoft" }));
    await waitFor(() => expect(go).toHaveBeenCalledWith(MICROSOFT));
    const sent = calls.find((c) => c.url === "/v1/auth/entra/start")?.body as { app: string; verifier: string };
    expect(sent.app).toBe("desktop");
    expect(sent.verifier).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(window.sessionStorage.getItem("lms.desktop.entra")).toBe(sent.verifier);
  });

  it("finishes when Microsoft sends them back, and opens the classroom", async () => {
    window.sessionStorage.setItem("lms.desktop.entra", "the-tabs-secret");
    const { calls } = stubApi((_method, url) => {
      if (url === "/v1/auth/entra/finish") return json(200, { token: "lms_s.mel", person: { ...MEL, method: "entra" } });
      if (url.startsWith("/v1/matrix")) return json(200, EMPTY);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/sign-in#entra=the-hand-off", false);
    expect(await screen.findByRole("heading", { name: "Classroom" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url === "/v1/auth/entra/finish").map((c) => c.body)).toEqual([
      { code: "the-hand-off", verifier: "the-tabs-secret" }]);
    expect(api.token).toBe("lms_s.mel");
    expect(window.sessionStorage.getItem("lms.desktop.entra")).toBeNull();
  });

  it("says plainly when nobody has that Microsoft account, and clears the address", async () => {
    stubApi((_method, url) => url === "/v1/auth/methods" ? json(200, ALL_ON) : null);
    renderApp("/sign-in#entra_error=not_matched", false);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nobody in Simple LMS has that Microsoft account. Ask your manager to add you.");
    expect(screen.getByTestId("where")).toHaveTextContent("/sign-in");
  });

  it("says so when the hand-off has expired", async () => {
    stubApi((_method, url) => url === "/v1/auth/entra/finish"
      ? json(401, { detail: "that Microsoft sign-in has finished or expired; try again" }) : null);
    renderApp("/sign-in#entra=too-late", false);
    expect(await screen.findByRole("alert")).toHaveTextContent("That Microsoft sign-in has finished or expired. Try again.");
  });

  it("sends a learner who signed in with Microsoft to the learner app", async () => {
    const { calls } = stubApi((_method, url) => url === "/v1/auth/entra/finish"
      ? json(200, { token: "lms_s.kim", person: { ...MEL, code: "LL042", permission: "learner", method: "entra" } }) : null);
    renderApp("/sign-in#entra=kims", false);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your training is in the learner app at /learn/.");
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/auth/logout")).toBe(true));
    expect(api.token).toBeNull();
  });

  it("offers only the ways that are on", async () => {
    stubApi((_method, url) => url === "/v1/auth/methods" ? json(200, { pin: true, password: false, entra: true }) : null);
    renderApp("/sign-in", false);
    expect(await screen.findByRole("button", { name: "Sign in with Microsoft" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
  });

  it("says what to do when every way into the desktop is off", async () => {
    stubApi((_method, url) => url === "/v1/auth/methods" ? json(200, { pin: true, password: false, entra: false }) : null);
    renderApp("/sign-in", false);
    expect(await screen.findByText(/lms clear-setting sign_in_password/)).toBeInTheDocument();
  });

  it("says when signing in with a password has been switched off", async () => {
    stubApi((_method, url) => url === "/v1/auth/login"
      ? json(403, { detail: "Signing in with an email and password is switched off here.", code: "method_off" }) : null);
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "mel@example.com.au");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Signing in with an email and password is switched off here\.$/);
  });
});
