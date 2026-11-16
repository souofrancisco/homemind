import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// API_PROXY_TARGET: em Docker aponta para o serviço backend.
const target = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": target, "/healthz": target } },
});
