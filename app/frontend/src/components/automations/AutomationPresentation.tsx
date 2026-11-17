import { Badge, Group, Stack, Text } from "@mantine/core";
import type { HomeRule, RuleDraft } from "../../types/home";

export function RuleActions({ rule }: { rule: HomeRule | RuleDraft }) {
  return <Stack gap="sm">
    {rule.acoes.map((action, index) => <Group key={`${action.dispositivo}-${index}`} justify="space-between" align="flex-start">
      <div>
        <Text fw={500}>{action.dispositivo === "lampada" ? "Luz" : "Tomada"}</Text>
        <Text size="sm" c="dimmed">
          {action.ligada ? "Ligar" : "Desligar"}
          {action.dispositivo === "lampada" && action.brilho != null ? ` com brilho a ${action.brilho}%` : ""}
          {action.dispositivo === "lampada" && action.cor ? `, em ${action.cor.replace("_", " ")}` : ""}
        </Text>
      </div>
      <Badge variant="light" color={action.ligada ? "yellow" : "gray"}>{action.ligada ? "Ligada" : "Desligada"}</Badge>
    </Group>)}
  </Stack>;
}

export function RuleTrigger({ object }: { object: string }) {
  return <Text>Quando levantar {object === "livro" ? "o livro" : object === "comando" ? "o comando" : object === "caneca" ? "a caneca" : object}</Text>;
}
