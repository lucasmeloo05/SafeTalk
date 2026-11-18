import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "@/context/auth-context";
import { GuestOnly, RequireAuth } from "@/components/auth-guards";
import { HomePage } from "@/pages/home";
import { LoginPage } from "@/pages/login";
import { OfficialModerationPage } from "@/pages/official-moderation";
import { RegisterPage } from "@/pages/register";
import { SocialPage } from "@/pages/social";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Navigate to="/app" replace />} />
          <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
          <Route path="/cadastro" element={<GuestOnly><RegisterPage /></GuestOnly>} />
          <Route path="/app" element={<RequireAuth><HomePage /></RequireAuth>} />
          <Route path="/pessoas" element={<RequireAuth><SocialPage /></RequireAuth>} />
          <Route path="/moderacao" element={<RequireAuth><OfficialModerationPage /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
