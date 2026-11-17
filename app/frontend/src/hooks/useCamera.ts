import { categoryOf } from "../utils/events";
import { useHome } from "./useHome";

/** Estado da câmara derivado do estado da casa e dos eventos recentes. */
export function useCamera() {
  const { state, events, online, simulated } = useHome();
  const detected = events.find((event) => categoryOf(event) === "object");
  const gesture = events.find((event) => categoryOf(event) === "gesture" || categoryOf(event) === "object");
  const activeMode = events.find((event) => categoryOf(event) === "mode");
  const mode = state?.mode_name ?? state?.mode ?? null;
  const cameraAvailable = false; // PRIV-02: a stream legacy não está ligada à API.
  const status = !online
    ? { title: "Backend offline", description: "A ligação ao serviço foi interrompida. O vídeo não está a ser atualizado.", color: "red" }
    : !state
      ? { title: "A obter estado da câmara", description: "A ligação está ativa; à espera do primeiro estado.", color: "blue" }
      : { title: "Captura de imagem desativada", description: "A visualização de câmara está desativada por PRIV-02.", color: "yellow" };
  const streamEnabled = false;
  return { state, online, simulated, streamEnabled, detected, gesture, activeMode, mode, cameraAvailable, status };
}
