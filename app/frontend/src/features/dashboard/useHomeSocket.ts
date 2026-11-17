import { useEffect, useState } from "react";
import { getHomeService } from "./homeApi";
import type { EventLogItem, HomeState } from "./types";

export function useHomeSocket() {
  const service = getHomeService();
  const [state, setState] = useState<HomeState | null>(null);
  const [events, setEvents] = useState<EventLogItem[]>([]);
  const [online, setOnline] = useState(false);
  useEffect(() => {
    let active = true;
    void service.getEvents().then((items) => { if (active) setEvents(items.slice(0, 50)); }).catch(() => undefined);
    const disconnect = service.connect((next) => setState(next), (event) => setEvents((current) => [event, ...current].slice(0, 50)), setOnline);
    return () => { active = false; disconnect(); };
  }, [service]);
  return { state, events, online, source: service.mode };
}
