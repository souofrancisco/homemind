import type { components } from "../../shared/api/schema";

export type Health = components["schemas"]["Health"];

export async function getHealth(): Promise<Health> {
  const r = await fetch("/healthz");
  if (!r.ok) throw new Error(`healthz ${r.status}`);
  return r.json();
}
