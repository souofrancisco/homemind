import { useEffect, useState } from "react";

type Poll<T> = { data: T | null; loading: boolean; offline: boolean; reload: () => void };

/** Atualização periódica. Em falha mantém os últimos dados e marca `offline` (nunca zera). */
export function usePolling<T>(key: string | undefined, load: (key: string) => Promise<T>, everyMs = 15000): Poll<T> {
  const [state, setState] = useState<{ key: string; data: T | null; offline: boolean } | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!key) return;
    let active = true;
    const run = () => load(key)
      .then((data) => active && setState({ key, data, offline: false }))
      .catch(() => active && setState((s) => ({ key, data: s?.key === key ? s.data : null, offline: true })));
    void run();
    const timer = setInterval(() => void run(), everyMs);
    return () => { active = false; clearInterval(timer); };
  }, [key, load, everyMs, tick]);
  const cur = state?.key === key ? state : null;
  return { data: cur?.data ?? null, loading: !cur, offline: cur?.offline ?? false, reload: () => setTick((n) => n + 1) };
}
