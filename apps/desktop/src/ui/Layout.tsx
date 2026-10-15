import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useGamePrefs } from "../lib/gamePrefs";
import { Classroom } from "../pages/Classroom";
import { Logo } from "./Logo";

/** The bar along the top, then the screen. In Game Mode the desktop opens
 * on the classroom; without it, on the matrix, as it did before. */
export function Layout() {
  const { me, can, signOut } = useAuth();
  const [prefs, setPrefs] = useGamePrefs();
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen">
      <header className="hdr">
        <div className="brand"><Logo />Simple LMS</div>
        <nav className="nav" aria-label="Screens">
          <NavLink to="/matrix">Matrix</NavLink>
          {can("people:read") && <NavLink to="/people">People</NavLink>}
          {can("roles:read") && <NavLink to="/roles">Roles</NavLink>}
          {can("competencies:read") && <NavLink to="/competencies">Competencies</NavLink>}
          {can("tickets:verify") && <NavLink to="/inbox">Inbox</NavLink>}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <button type="button" className="btn" aria-pressed={prefs.classroom} onClick={() => setPrefs({ classroom: !prefs.classroom })}
                  title="The classroom, just for you on this computer">Game Mode</button>
          <span className="small">{me?.name} · {me?.permission}</span>
          <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      {prefs.classroom && pathname === "/" ? <Classroom /> : <Outlet />}
    </div>
  );
}
