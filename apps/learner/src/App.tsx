import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { SessionProvider, useSession } from "./auth/Session";
import { AddTicket } from "./pages/AddTicket";
import { ModulePlayer } from "./pages/ModulePlayer";
import { MyTraining } from "./pages/MyTraining";
import { SignOff, SignOffPeople } from "./pages/SignOff";
import { SignPolicy } from "./pages/SignPolicy";
import { SignIn } from "./pages/SignIn";

function RequirePerson() {
  const { person } = useSession();
  return person ? <Outlet /> : <Navigate to="/sign-in" replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route element={<RequirePerson />}>
        <Route index element={<MyTraining />} />
        <Route path="/sign/:key" element={<SignPolicy />} />
        <Route path="/ticket/:key" element={<AddTicket />} />
        <Route path="/module/:key" element={<ModulePlayer />} />
        <Route path="/signoff" element={<SignOffPeople />} />
        <Route path="/signoff/:code/:key" element={<SignOff />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter basename="/learn">
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </BrowserRouter>
  );
}
