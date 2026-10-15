/** Every screen the desktop has, in the order the bar along the top shows
 * them, with the scope that shows each. In Game Mode each opens as a drawer
 * over the classroom, named from here, so the bar and the drawer never disagree.
 * A screen a later step adds is a line here and its route in App.tsx. */
export interface Screen { to: string; label: string; scope: string }

export const SCREENS: Screen[] = [
  { to: "/matrix", label: "Matrix", scope: "matrix:read" },
  { to: "/people", label: "People", scope: "people:read" },
  { to: "/roles", label: "Roles", scope: "roles:read" },
  { to: "/competencies", label: "Competencies", scope: "competencies:read" },
  { to: "/inbox", label: "Inbox", scope: "tickets:verify" },
];

/** The drawer's name for a path: the screen it is, or under. */
export function screenTitle(pathname: string): string {
  return SCREENS.find((s) => pathname === s.to || pathname.startsWith(`${s.to}/`))?.label ?? "Simple LMS";
}
