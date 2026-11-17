import { useMemo, useState } from "react";
import type { EventGroup } from "../types/home";
import { categoryOf, eventGroups, eventTime } from "../utils/events";
import { useHome } from "./useHome";

const pageLoadedAt = Date.now();

/** Histórico de eventos: pesquisa, filtros, agrupamento por operação e paginação (por eventos, sem partir grupos). */
export function useEvents() {
  const { events, online } = useHome();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [period, setPeriod] = useState<string | null>("7d");
  const [pageSize, setPageSize] = useState("10");
  const [page, setPage] = useState(1);
  const pageLimit = Number(pageSize) || 10;

  const filtered = useMemo(() => {
    const cutoff = period === "24h" ? pageLoadedAt - 86400000 : period === "7d" ? pageLoadedAt - 7 * 86400000 : 0;
    const needle = search.trim().toLocaleLowerCase("pt-PT");
    return events.filter((event) => {
      const timestamp = eventTime(event);
      return (!needle || event.message.toLocaleLowerCase("pt-PT").includes(needle))
        && (!category || categoryOf(event) === category)
        && (!level || event.level === level)
        && Number.isFinite(timestamp) && timestamp >= cutoff;
    });
  }, [events, search, category, level, period]);

  const pages = useMemo(() => {
    const result: EventGroup[][] = [];
    let current: EventGroup[] = [];
    let count = 0;
    for (const group of eventGroups(filtered)) {
      const size = group.events.length;
      if (current.length && count + size > pageLimit) {
        result.push(current);
        current = [];
        count = 0;
      }
      current.push(group);
      count += size;
    }
    if (current.length) result.push(current);
    return result;
  }, [filtered, pageLimit]);

  const pageCount = Math.max(1, pages.length);
  const safePage = Math.min(page, pageCount);
  const currentGroups = pages[safePage - 1] ?? [];
  const shown = currentGroups.reduce((sum, group) => sum + group.events.length, 0);
  const first = shown ? pages.slice(0, safePage - 1).reduce((sum, entry) => sum + entry.reduce((n, group) => n + group.events.length, 0), 0) + 1 : 0;
  const hasFilters = Boolean(search.trim() || category || level || period !== "all");

  // Qualquer alteração de filtro volta à primeira página.
  const filter = <T,>(set: (value: T) => void) => (value: T) => { set(value); setPage(1); };
  const clearFilters = () => { setSearch(""); setCategory(null); setLevel(null); setPeriod("all"); setPage(1); };

  return {
    online, hasEvents: events.length > 0, filtered: filtered.length, currentGroups, pageCount, page: safePage, setPage,
    range: { first, last: first ? first + shown - 1 : 0 },
    filters: { search, category, level, period, hasFilters, clear: clearFilters,
      setSearch: filter(setSearch), setCategory: filter(setCategory), setLevel: filter(setLevel), setPeriod: filter(setPeriod) },
    pageSize, setPageSize: filter(setPageSize),
  };
}
