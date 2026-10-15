import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { Competencies } from "./pages/Competencies";
import { Inbox } from "./pages/Inbox";
import { Matrix } from "./pages/Matrix";
import { People } from "./pages/People";
import { Roles } from "./pages/Roles";
import { Settings } from "./pages/Settings";
import { SignIn } from "./pages/SignIn";
import { Layout } from "./ui/Layout";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Matrix />} />
          <Route path="/people" element={<People />} />
          <Route path="/roles" element={<Roles />} />
          <Route path="/competencies" element={<Competencies />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
