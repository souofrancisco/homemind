import { Badge, Group } from "@mantine/core";

type Origin = "real" | "simulated";
type Kind = "measured" | "estimated" | "inferred";

export default function OriginBadge({ origin, kind, demo = false }: { origin: Origin; kind?: Kind; demo?: boolean }) {
  if (demo && origin === "simulated") return null;
  const real = origin === "real";
  const label = real ? "REAL" : "SIMULADO";
  const color = origin === "real" ? "teal" : "orange";
  const kindLabel = kind === "measured" ? "Medido" : kind === "estimated" ? "Estimado" : kind === "inferred" ? "Inferido" : null;
  return <Group gap={4} component="span" wrap="nowrap"><Badge color={color} variant="light" styles={{ label: { color: real ? "light-dark(#05563f, var(--mantine-color-teal-3))" : "light-dark(#8f3400, var(--mantine-color-orange-3))" } }}>{label}</Badge>{kindLabel && <Badge color="gray" variant="light">{kindLabel}</Badge>}</Group>;
}
