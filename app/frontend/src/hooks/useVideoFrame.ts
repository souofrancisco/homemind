import { useEffect, useState } from "react";
import { streamVideo } from "../services/home/video";

/** URL (blob) do frame mais recente de GET /api/video; `error` se o stream falhar. Reabre com pausa enquanto `enabled`. */
export function useVideoFrame(enabled: boolean) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    let current: string | null = null;
    const show = (jpeg: Blob) => {
      const next = URL.createObjectURL(jpeg);
      if (current) URL.revokeObjectURL(current);
      current = next;
      setUrl(next);
    };
    void (async () => {
      while (!abort.signal.aborted) {
        try { setError(null); await streamVideo(show, abort.signal); }
        catch (e) { if (abort.signal.aborted) return; setError(e instanceof Error ? e.message : "Stream indisponível"); }
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    })();
    return () => { abort.abort(); if (current) URL.revokeObjectURL(current); setUrl(null); };
  }, [enabled]);
  return { url: enabled ? url : null, error: enabled ? error : null };
}
