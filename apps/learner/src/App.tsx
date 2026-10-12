import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { SessionProvider, useSession } from "./auth/Session";
import { MyTraining } from "./pages/MyTraining";
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
