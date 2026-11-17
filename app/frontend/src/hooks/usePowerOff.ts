import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { homeService } from "../services/home";

/** "Desligar tudo": devolve `run`, que resolve `true` quando o pedido foi concluído. */
export function usePowerOff() {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const result = await homeService.turnOff();
      notifications.show({ color: result.success ? "teal" : "orange", title: result.success ? result.backend === "fake" ? "Demonstração concluída" : "Pedido concluído" : "Resultado incompleto", message: result.message });
      return result.success;
    } catch {
      notifications.show({ color: "red", title: "Não foi possível desligar", message: "Tenta novamente mais tarde." });
      return false;
    } finally { setBusy(false); }
  };
  return { busy, run };
}
