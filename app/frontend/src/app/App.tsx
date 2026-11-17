import { Center, Loader } from "@mantine/core";
import { useEffect, type ReactNode } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
import Shell from "../components/layout/Shell";
import { completeLogin } from "../services/auth/oidc";
import { useAuth } from "./providers/AuthProvider";
import { HomeProvider } from "./providers/HomeProvider";

function Protected({ children }: { children: ReactNode }) {
  const { user, login } = useAuth();
  useEffect(() => {
    if (!user) void login();
  }, [user, login]);
  return user ? (
    children
  ) : (
    <Center h="100dvh">
      <Loader />
    </Center>
  );
}

function Callback() {
  const navigate = useNavigate();
  useEffect(() => {
    completeLogin()
      .then((u) => navigate(typeof u?.state === "string" && u.state !== "/auth/callback" ? u.state : "/", { replace: true }))
      .catch(() => navigate("/", { replace: true }));
  }, [navigate]);
  return null;
}

export default function App() {
  return (
    <Routes>
      <Route path="/auth/callback" element={<Callback />} />
      <Route
        path="*"
        element={
          <Protected>
            <HomeProvider>
              <Shell />
            </HomeProvider>
          </Protected>
        }
      />
    </Routes>
  );
}
