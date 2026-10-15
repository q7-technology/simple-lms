import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Logo } from "./Logo";

/** Until Game Mode (build step 7) the desktop opens on the matrix. */
export function Layout() {
  const { me, can, signOut } = useAuth();
  return (
    <div className="min-h-screen">
      <header className="hdr">
        <div className="brand"><Logo />Simple LMS</div>
        <nav className="nav" aria-label="Screens">
          <NavLink to="/" end>Matrix</NavLink>
          {can("people:read") && <NavLink to="/people">People</NavLink>}
          {can("roles:read") && <NavLink to="/roles">Roles</NavLink>}
          {can("competencies:read") && <NavLink to="/competencies">Competencies</NavLink>}
          {can("tickets:verify") && <NavLink to="/inbox">Inbox</NavLink>}
          {can("settings:write") && <NavLink to="/settings">Settings</NavLink>}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="small">{me?.name} · {me?.permission}</span>
          <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
