export type Health = { status: string; mode: "simulation" | "real"; physical_writes: boolean };

export async function getHealth(): Promise<Health> {
  const r = await fetch("/healthz");
  if (!r.ok) throw new Error(`healthz ${r.status}`);
  return r.json();
}
