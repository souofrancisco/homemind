import { useEffect, useMemo, useState, type ReactNode } from "react";
import { HomeContext } from "../../hooks/useHome";
import { homeService } from "../../services/home";
import type { EventLogItem, HomeState } from "../../types/home";

const newestFirst = (items: EventLogItem[]) => [...items].sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp));

// Única ligação WebSocket (ou mock) partilhada por toda a app.
export function HomeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<HomeState | null>(null);
  const [events, setEvents] = useState<EventLogItem[]>([]);
  const [online, setOnline] = useState(false);
  useEffect(() => {
    let active = true;
    // Histórico (também após cada reconexão, para recuperar o que passou enquanto estava offline).
    const loadEvents = () => homeService.getEvents().then((items) => {
      if (active) setEvents((current) => newestFirst([...items, ...current]).filter((item, index, all) => all.findIndex((candidate) => candidate.id === item.id) === index).slice(0, 50));
    }).catch(() => undefined);
    // Estado inicial por REST: não depende só do WebSocket (que depois o mantém atualizado).
    void homeService.getState().then((next) => { if (active) setState((current) => current ?? next); }).catch(() => undefined);
    void loadEvents();
    const disconnect = homeService.connect(
      (next) => { if (active) setState(next); },
      (event) => { if (active) setEvents((current) => newestFirst([event, ...current.filter((item) => item.id !== event.id)]).slice(0, 50)); },
      (connected) => { if (active) { setOnline(connected); if (connected) void loadEvents(); } },
    );
    return () => { active = false; disconnect(); };
  }, []);
  const value = useMemo(
    () => ({ state, events, online, source: homeService.mode, mock: homeService.mode === "mock", simulated: homeService.mode === "mock" || state?.backend === "fake" }),
    [state, events, online],
  );
  return <HomeContext.Provider value={value}>{children}</HomeContext.Provider>;
}
