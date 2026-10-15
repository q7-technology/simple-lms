import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useGamePrefs } from "../lib/gamePrefs";
import { Classroom } from "../pages/Classroom";
import { rememberOpener } from "./focusReturn";
import { ClassroomBackdrop } from "./ClassroomArt";
import { Logo } from "./Logo";
import { ScreenPanel } from "./ScreenPanel";
import { SCREENS } from "./screens";

/** The bar along the top, then the screen. In Game Mode the desktop opens
 * on the classroom and every screen is a drawer over it; without it, on
 * the matrix, with each screen a page, as it was before. */
export function Layout() {
  const { me, can, signOut } = useAuth();
  const [prefs, setPrefs] = useGamePrefs();
  const { pathname } = useLocation();
  const header = (
    // a screen opened from the bar gives focus back to the classroom's heading
    <header className="hdr" onClickCapture={() => rememberOpener(null)}>
      <div className="brand"><Logo />Simple LMS</div>
      <nav className="nav" aria-label="Screens">
        {SCREENS.filter((s) => can(s.scope)).map((s) => <NavLink key={s.to} to={s.to}>{s.label}</NavLink>)}
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <button type="button" className="btn" aria-pressed={prefs.classroom} onClick={() => setPrefs({ classroom: !prefs.classroom })}
                title="The classroom, just for you on this computer">Game Mode</button>
        <span className="small">{me?.name} · {me?.permission}</span>
        <button type="button" className="btn" onClick={() => void signOut()}>Sign out</button>
      </div>
    </header>
  );
  if (!prefs.classroom) {
    return <div className="min-h-screen">{header}<Outlet /></div>;
  }
  return (
    <div className="app">
      {header}
      <div className="stage">
        {pathname === "/" ? <Classroom /> : <><ClassroomBackdrop /><ScreenPanel><Outlet /></ScreenPanel></>}
      </div>
    </div>
  );
}
