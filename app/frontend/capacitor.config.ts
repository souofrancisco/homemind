import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "pt.homemind.app",
  appName: "Conta Certa",
  webDir: "dist",
  android: { adjustMarginsForEdgeToEdge: "auto" },
  // Pedidos nativos: sem CORS nem bloqueio de HTTP em dev. Backend/Authentik por HTTP no LAN/adb reverse.
  server: { cleartext: true },
  plugins: { CapacitorHttp: { enabled: true } },
};

export default config;
