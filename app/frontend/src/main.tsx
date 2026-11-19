import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import { MantineProvider, createTheme } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./app/App";
import { AuthProvider } from "./app/providers/AuthProvider";

const theme = createTheme({
  fontFamily: '"DM Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  headings: { fontFamily: '"DM Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif', fontWeight: "700" },
  defaultRadius: "md",
  radius: { lg: "20px", xl: "28px" },
  autoContrast: true,
  primaryColor: "ink",
  primaryShade: { light: 9, dark: 0 },
  colors: { ink: ["#f3f4f6", "#e5e7eb", "#d1d5db", "#9ca3af", "#6b7280", "#4b5563", "#374151", "#25282e", "#1c1e23", "#16181d"] },
  components: {
    Button: { defaultProps: { radius: "xl", color: "ink" } },
    Card: { defaultProps: { radius: "lg", withBorder: true } },
    Badge: { defaultProps: { radius: "xl", color: "gray", variant: "light" } },
    ThemeIcon: { defaultProps: { color: "gray" } },
    NavLink: { defaultProps: { radius: "xl" } },
    Anchor: { defaultProps: { c: "inherit", underline: "always" } },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <Notifications position="top-center" limit={3} autoClose={5000} />
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </MantineProvider>
  </StrictMode>,
);
