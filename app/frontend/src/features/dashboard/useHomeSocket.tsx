import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getHomeService } from "./homeApi";
import type { EventLogItem, HomeState } from "./types";

const service = getHomeService();
type HomeData = { state: HomeState | null; events: EventLogItem[]; online: boolean; source: "mock" | "api" };
const HomeContext = createContext<HomeData | null>(null);

export function normalizeEvent(event: EventLogItem): EventLogItem {
  return { ...event };
}

const newestFirst = (items: EventLogItem[]) => [...items].sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp));

export function HomeDataProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<HomeState | null>(null);
  const [events, setEvents] = useState<EventLogItem[]>([]);
  const [online, setOnline] = useState(false);
  useEffect(() => {
    let active = true;
    void service.getEvents().then((items) => {
      if (active) setEvents((current) => newestFirst([...items.map(normalizeEvent), ...current]).filter((item, index, all) => all.findIndex((candidate) => candidate.id === item.id) === index).slice(0, 50));
    }).catch(() => undefined);
    const disconnect = service.connect(
      (next) => { if (active) setState(next); },
      (event) => { if (active) setEvents((current) => newestFirst([normalizeEvent(event), ...current.filter((item) => item.id !== event.id)]).slice(0, 50)); },
      (connected) => { if (active) setOnline(connected); },
    );
    return () => { active = false; disconnect(); };
  }, []);
  const value = useMemo(() => ({ state, events, online, source: service.mode }), [state, events, online]);
  return <HomeContext.Provider value={value}>{children}</HomeContext.Provider>;
}

export function useHomeSocket() {
  const value = useContext(HomeContext);
  if (!value) throw new Error("useHomeSocket tem de ser usado dentro de HomeDataProvider");
  return value;
}
