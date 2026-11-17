import { accessToken, apiBase } from "../api/client";

const decoder = new TextDecoder();
const HEADER_END = [13, 10, 13, 10];

function indexOfHeaderEnd(buf: Uint8Array): number {
  for (let i = 0; i + 3 < buf.length; i++) if (HEADER_END.every((b, k) => buf[i + k] === b)) return i;
  return -1;
}

/**
 * Lê GET /api/video (MJPEG multipart) com Bearer e entrega cada frame JPEG como Blob.
 * Um <img src> não envia cabeçalhos e o token nunca vai no URL. Resolve quando o stream acaba; lança em erro HTTP.
 */
export async function streamVideo(onFrame: (jpeg: Blob) => void, signal: AbortSignal): Promise<void> {
  const token = await accessToken();
  if (!token) throw new Error("Sem sessão");
  const response = await fetch(`${apiBase}/api/video`, { headers: { Authorization: `Bearer ${token}` }, signal });
  if (!response.ok || !response.body) throw new Error(response.status === 503 ? "Sem fonte de vídeo configurada" : `Erro ${response.status}`);
  const reader = response.body.getReader();
  let buf = new Uint8Array(0);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    const next = new Uint8Array(buf.length + value.length);
    next.set(buf); next.set(value, buf.length);
    buf = next;
    for (;;) {
      const end = indexOfHeaderEnd(buf);
      if (end < 0) break;
      const length = Number(/content-length:\s*(\d+)/i.exec(decoder.decode(buf.subarray(0, end)))?.[1]);
      if (!Number.isFinite(length)) { buf = buf.subarray(end + 4); continue; }
      if (buf.length < end + 4 + length) break;
      onFrame(new Blob([buf.slice(end + 4, end + 4 + length)], { type: "image/jpeg" }));
      buf = buf.subarray(end + 4 + length);
    }
  }
}
