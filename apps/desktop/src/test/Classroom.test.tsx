import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Matrix, MatrixRow, Person } from "../api/types";
import { GAME_PREFS_KEY } from "../lib/gamePrefs";
import { MEL, json, renderApp, stubApi } from "./harness";

const PICKER = { key: "picker", name: "Picker" };
const FORKLIFT = { key: "forklift-operator", name: "Forklift operator" };
const LICENCE = { key: "forklift-licence", name: "Forklift licence", kind: "ticket" as const };

function person(code: string, name: string, roles: { key: string; name: string }[],
                status: "current" | "missing" | "not_required"): MatrixRow {
  return { code, name, roles, supervisor: null, cells: { "forklift-licence": { status, granted_on: null, expires_on: null } } };
}

const ROOM: Matrix = {
  today: "2026-10-12",
  competencies: [LICENCE],
  people: [
    person("LL050", "Ana Diaz", [PICKER], "current"),
    person("LL042", "Kim Lee", [PICKER, FORKLIFT], "missing"),
    person("LL060", "Zed Ng", [], "not_required"),
  ],
};

const KIM: Person = {
  id: 4, code: "LL042", name: "Kim Lee", email: null, permission: "learner", supervisor: null,
  roles: [PICKER, FORKLIFT], active: true, has_pin: true, pin_locked: false, has_password: false,
};

const SUPERVISOR = { ...MEL, permission: "supervisor" as const, scopes: ["training:read", "matrix:read", "roles:read"] };

/** The matrix answers with `matrix`; the matrix's and People's lists, and Kim, are there to open. */
function stubRoom(matrix: Matrix = ROOM, me = MEL) {
  return stubApi((_m, url) => {
    if (url.startsWith("/v1/matrix")) return json(200, matrix);
    if (url === "/v1/roles") return json(200, { items: [{ ...PICKER, competencies: [], people: 2 }], total: 1 });
    if (url.startsWith("/v1/people?")) return json(200, { items: [KIM], total: 1 });
    if (url === "/v1/people/LL042") return json(200, KIM);
    if (url === "/v1/people/LL042/overrides") return json(200, []);
    return null;
  }, me);
}

const tones = (svg: Element) => [...svg.querySelectorAll("[data-tone]")].map((f) => f.getAttribute("data-tone"));

describe("the classroom", () => {
  it("has a desk for each role, with its people sitting at it, those who need a look first", async () => {
    stubRoom();
    const { container } = renderApp("/");
    expect(await screen.findByRole("heading", { name: "Classroom" })).toBeInTheDocument();
    expect(await screen.findByText("3 people: 1 current, 1 need training, 1 nothing due")).toBeInTheDocument();
    const desks = within(screen.getByRole("list", { name: "Desks" }));
    expect(desks.getAllByRole("link", { name: /Open in the matrix$/ }).map((d) => d.getAttribute("aria-label"))).toEqual([
      "Forklift operator: 1 person, 1 need training. Open in the matrix",
      "Picker: 2 people, 1 current, 1 need training. Open in the matrix",
    ]);
    // drawn back to front: Kim at the forklift desk, then Kim (first: she needs training) and Ana at the picker desk
    expect(tones(container.querySelector(".roompic")!)).toEqual(["red", "red", "green"]);
    // Zed has no role, so no desk: he is counted, and People is a click away
    expect(screen.getByText(/1 person has no role yet, so no desk\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Give them one under People" })).toHaveAttribute("href", "/people");
  });

  it("opens the matrix at a desk's role", async () => {
    const { calls } = stubRoom();
    renderApp("/");
    await userEvent.click(await screen.findByRole("link", { name: /^Picker: / }));
    expect(screen.getByTestId("where")).toHaveTextContent("/matrix");
    expect(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" })).toBeInTheDocument();
    expect(calls.filter((c) => c.url.startsWith("/v1/matrix")).at(-1)?.url).toBe("/v1/matrix?role=picker");
    expect(screen.getByLabelText("Role")).toHaveValue("picker");
  });

  it("opens a person from where they sit", async () => {
    stubRoom();
    renderApp("/");
    const desk = await screen.findByRole("list", { name: "At the Picker desk" });
    await userEvent.click(within(desk).getByRole("link", { name: "Kim Lee: need training" }));
    expect(screen.getByTestId("where")).toHaveTextContent("/people");
    const kim = await screen.findByRole("dialog", { name: "Kim Lee" });
    // her drawer keeps focus: the screen's way back is behind it
    expect(kim).toContainElement(document.activeElement as HTMLElement);
    // and gives it back to the way back to the classroom when it closes
    await userEvent.click(within(kim).getByRole("button", { name: "Close" }));
    expect(screen.getByRole("link", { name: "Back to the classroom" })).toHaveFocus();
  });

  it("seats six at a desk and counts the rest", async () => {
    const crowd = Array.from({ length: 18 }, (_, i) => person(`P${i + 10}`, `Person ${i + 10}`, [PICKER], "current"));
    stubRoom({ ...ROOM, people: crowd });
    const { container } = renderApp("/");
    const desk = await screen.findByRole("link", { name: /^Picker: 18 people/ });
    expect(desk).toHaveTextContent("Picker+12");
    expect(container.querySelectorAll(".roompic [data-tone]")).toHaveLength(6);
    expect(within(screen.getByRole("list", { name: "At the Picker desk" })).getAllByRole("link")).toHaveLength(6);
  });

  it("says when there are no desks yet", async () => {
    stubRoom({ ...ROOM, people: [] });
    renderApp("/");
    expect(await screen.findByText(/No desks yet\. Add roles, then give people roles under People/)).toBeInTheDocument();
  });

  it("shows a supervisor their team's desks, without the people links they can't open", async () => {
    stubRoom(ROOM, SUPERVISOR);
    renderApp("/");
    expect(await screen.findByRole("link", { name: /^Picker: / })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "At the Picker desk" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Give them one under People" })).not.toBeInTheDocument();
  });

  it("tells a supervisor when nobody in their team has a desk", async () => {
    stubRoom({ ...ROOM, people: [] }, SUPERVISOR);
    renderApp("/");
    expect(await screen.findByText("Nobody in your team has a role yet, so no desks.")).toBeInTheDocument();
  });

  it("turns Game Mode off in one click, and then the desktop opens on the matrix", async () => {
    stubRoom();
    const { unmount } = renderApp("/");
    const game = await screen.findByRole("button", { name: "Game Mode" });
    expect(game).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(game);
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/matrix");
    expect(game).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(GAME_PREFS_KEY)).toBe('{"classroom":false}');
    unmount();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Matrix" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Classroom" })).not.toBeInTheDocument();
  });
});

describe("screens over the classroom", () => {
  it("opens each screen as a drawer over the classroom, named as the bar names it", async () => {
    stubRoom();
    renderApp("/people");
    const drawer = await screen.findByRole("region", { name: "People" });
    expect(within(drawer).getByRole("heading", { name: "People" })).toBeInTheDocument();
    // keyboard users start in the drawer, at the way back
    const back = screen.getByRole("link", { name: "Back to the classroom" });
    expect(back).toHaveFocus();
    // the bar stays: the matrix is one click away
    expect(within(screen.getByRole("navigation", { name: "Screens" })).getByRole("link", { name: "Matrix" })).toBeInTheDocument();
    await userEvent.click(back);
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
    expect(await screen.findByRole("heading", { name: "Classroom" })).toHaveFocus();
  });

  it("goes back to the classroom on Escape, once a drawer inside it has closed", async () => {
    stubApi((_m, url) => {
      if (url.startsWith("/v1/matrix")) return json(200, ROOM);
      if (url === "/v1/roles") return json(200, { items: [], total: 0 });
      if (url.startsWith("/v1/people/LL042/records")) return json(200, []);
      return null;
    });
    renderApp("/matrix");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee, Forklift licence: Missing" }));
    expect(await screen.findByRole("dialog", { name: "Forklift licence" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/matrix");
    await userEvent.keyboard("{Escape}");
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });

  it("gives focus back to the desk that opened the screen", async () => {
    stubRoom();
    renderApp("/");
    await userEvent.click(await screen.findByRole("link", { name: /^Picker: / }));
    await screen.findByRole("region", { name: "Matrix" });
    await userEvent.click(screen.getByRole("link", { name: "Back to the classroom" }));
    await waitFor(() => expect(screen.getByRole("link", { name: /^Picker: / })).toHaveFocus());
  });

  it("keeps each screen a page of its own with Game Mode off", async () => {
    window.localStorage.setItem(GAME_PREFS_KEY, '{"classroom":false}');
    stubRoom();
    renderApp("/people");
    expect(await screen.findByRole("heading", { name: "People" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "People" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Back to the classroom" })).not.toBeInTheDocument();
  });
});

describe("the address keeps up with what is open", () => {
  it("drops the person from the address when their drawer closes", async () => {
    stubRoom();
    renderApp("/people?person=LL042");
    const kim = await screen.findByRole("dialog", { name: "Kim Lee" });
    await userEvent.click(within(kim).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("search")).toBeEmptyDOMElement();
  });

  it("puts a person opened from the list in the address", async () => {
    stubRoom();
    renderApp("/people");
    await userEvent.click(await screen.findByRole("button", { name: "Kim Lee" }));
    expect(await screen.findByRole("dialog", { name: "Kim Lee" })).toBeInTheDocument();
    expect(screen.getByTestId("search")).toHaveTextContent("?person=LL042");
  });

  it("keeps the matrix's role in the address", async () => {
    stubRoom();
    renderApp("/matrix?role=picker");
    const role = await screen.findByLabelText("Role");
    await screen.findByRole("option", { name: "Picker" });
    expect(role).toHaveValue("picker");
    await userEvent.selectOptions(role, "");
    expect(screen.getByTestId("search")).toBeEmptyDOMElement();
    await userEvent.selectOptions(role, "picker");
    expect(screen.getByTestId("search")).toHaveTextContent("?role=picker");
  });
});
