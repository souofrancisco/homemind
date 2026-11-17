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
      const lamp = result.devices.lampada === "off" ? "lâmpada desligada" : "lâmpada sem confirmação";
      const plug = result.devices.tomada === "off" ? "tomada desligada" : "tomada sem confirmação";
      const simulated = result.backend === "fake";
      notifications.show({
        color: result.success ? "teal" : "orange",
        title: result.success ? (simulated ? "Desligado (simulado)" : "Desligado e confirmado") : "Resultado incompleto",
        message: `${result.message ?? (simulated ? "Simulação: nenhum dispositivo físico foi alterado." : "Dispositivos confirmados.")} (${lamp}, ${plug})`,
      });
      return result.success;
    } catch {
      notifications.show({ color: "red", title: "Não foi possível desligar", message: "Tenta novamente mais tarde." });
      return false;
    } finally { setBusy(false); }
  };
  return { busy, run };
}
