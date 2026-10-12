import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { json, MEL, renderApp, stubApi } from "./harness";

const EMPTY = { today: "2026-10-12", competencies: [], people: [] };

describe("signing in to the desktop", () => {
  afterEach(() => window.localStorage.clear());

  it("sends someone not signed in to the sign-in page", async () => {
    stubApi();
    renderApp("/", false);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("signs a manager in and opens the matrix", async () => {
    const { calls } = stubApi((_method, url) => {
      if (url === "/v1/auth/login") return json(200, { token: "lms_s.new", person: MEL });
      if (url.startsWith("/v1/matrix")) return json(200, EMPTY);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      return null;
    });
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "mel@example.com.au");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
    expect(api.token).toBe("lms_s.new");
    expect(calls.find((c) => c.url === "/v1/auth/login")?.body).toEqual({
      email: "mel@example.com.au", password: "correct horse battery" });
  });

  it("says plainly when the password is wrong", async () => {
    stubApi((_method, url) => url === "/v1/auth/login"
      ? json(401, { detail: "wrong email or password", code: "wrong_password" }) : null);
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "mel@example.com.au");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
  });

  it("sends a learner to the learner app and signs them out again", async () => {
    const { calls } = stubApi((_method, url) => url === "/v1/auth/login"
      ? json(200, { token: "lms_s.kim", person: { ...MEL, code: "LL042", permission: "learner", scopes: ["training:read"] } })
      : null);
    renderApp("/sign-in", false);
    await userEvent.type(await screen.findByLabelText("Email"), "kim@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your training is in the learner app at /learn/.");
    await waitFor(() => expect(calls.some((c) => c.url === "/v1/auth/logout")).toBe(true));
    expect(api.token).toBeNull();
  });
});
