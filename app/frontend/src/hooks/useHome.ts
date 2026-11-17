import { createContext, useContext } from "react";
import type { EventLogItem, HomeState } from "../types/home";

export type HomeData = {
  state: HomeState | null;
  events: EventLogItem[];
  online: boolean;
  source: "mock" | "api";
  /** Backend a usar dados de exemplo: não altera dispositivos reais. */
  simulated: boolean;
};

export const HomeContext = createContext<HomeData | null>(null);

export function useHome() {
  const value = useContext(HomeContext);
  if (!value) throw new Error("useHome tem de ser usado dentro de HomeProvider");
  return value;
}
