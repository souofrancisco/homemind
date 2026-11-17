import { categoryOf } from "../utils/events";
import { useHome } from "./useHome";

/** Estado da câmara derivado do estado da casa e dos eventos recentes. */
export function useCamera() {
  const { state, events, online, simulated, mock } = useHome();
  const detected = events.find((event) => categoryOf(event) === "object");
  const gesture = events.find((event) => categoryOf(event) === "gesture" || categoryOf(event) === "object");
  const activeMode = events.find((event) => categoryOf(event) === "mode");
  const mode = state?.mode_name ?? state?.mode ?? null;
  const cameraAvailable = Boolean(state?.camera_ok);
  const status = !online
    ? { title: "Backend offline", description: "A ligação ao serviço foi interrompida. O vídeo não está a ser atualizado.", color: "red" }
    : !state
      ? { title: "A obter estado da câmara", description: "A ligação está ativa; à espera do primeiro estado.", color: "blue" }
      : !cameraAvailable
        ? { title: "Câmara indisponível", description: "O backend está ligado, mas não comunica uma câmara disponível.", color: "yellow" }
        : { title: "Câmara disponível", description: "A aguardar o primeiro frame do backend.", color: "teal" };
  // Só pede o stream com backend real ligado e câmara comunicada como disponível.
  const streamEnabled = !mock && online && cameraAvailable;
  return { state, online, simulated, streamEnabled, detected, gesture, activeMode, mode, cameraAvailable, status };
}
