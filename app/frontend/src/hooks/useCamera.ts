import { useHome } from "./useHome";

/** Estado da câmara derivado do estado da casa e dos eventos recentes. */
export function useCamera() {
  const { state, events, online, simulated } = useHome();
  const detected = events.find((event) => event.category === "object" || /objeto detetado/i.test(event.message));
  const gesture = events.find((event) => event.category === "gesture" || /gesto validado/i.test(event.message));
  const activeMode = events.find((event) => event.category === "mode" || /modo .* ativado|ações previstas/i.test(event.message));
  const mode = state?.mode_name ?? state?.mode ?? null;
  const cameraAvailable = Boolean(state?.camera_ok);
  const status = !online
    ? { title: "Backend offline", description: "A ligação ao serviço foi interrompida. O vídeo não está a ser atualizado.", color: "red" }
    : !state
      ? { title: "A obter estado da câmara", description: "A ligação está ativa; à espera do primeiro estado.", color: "blue" }
      : !cameraAvailable
        ? { title: "Câmara indisponível", description: "O backend está ligado, mas não comunica uma câmara disponível.", color: "yellow" }
        : { title: "Câmara disponível · stream por configurar", description: "A origem MJPEG ainda não foi confirmada. Nenhuma rota de vídeo foi solicitada.", color: "teal" };
  return { state, online, simulated, detected, gesture, activeMode, mode, cameraAvailable, status };
}
