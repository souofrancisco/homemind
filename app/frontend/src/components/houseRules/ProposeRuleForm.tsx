import { Alert, Button, Card, NumberInput, Radio, Select, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";
import type { AutomationProposeIn } from "../../services/automations/api";

export type PlugOption = { value: string; label: string };

type Props = { plugs: PlugOption[]; busy: boolean; simulated: boolean; onSubmit: (body: AutomationProposeIn) => Promise<boolean> };

export default function ProposeRuleForm({ plugs, busy, simulated, onSubmit }: Props) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"power_above" | "presence_changed">("power_above");
  const [watts, setWatts] = useState<number | string>("");
  const [minutes, setMinutes] = useState<number | string>("");
  const [meter, setMeter] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);

  const power = kind === "power_above";
  const valid = name.trim() !== "" && target != null && (!power || (meter != null && Number(watts) > 0 && minutes !== "" && Number(minutes) >= 0));
  const submit = async () => {
    const trigger = power
      ? { kind, device_id: meter, threshold_w: Number(watts), duration_s: Math.round(Number(minutes) * 60) }
      : { kind };
    if (await onSubmit({ name: name.trim(), trigger, target_device_id: target! })) {
      setName(""); setWatts(""); setMinutes(""); setMeter(null); setTarget(null);
    }
  };
  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="md">
        <Title order={3} size="h4">Propor regra</Title>
        <Text size="sm" c="dimmed">A regra só desliga uma tomada. Só fica ativa se a maioria dos moradores votar a favor em 24 h.{simulated ? " Nesta casa de demonstração a execução é SIMULADA." : ""}</Text>
        {!plugs.length ? <Alert icon={<IconInfoCircle />} color="gray">Ainda não há tomadas conhecidas nesta casa, por isso não é possível propor regras.</Alert> : (
          <>
            <TextInput label="Nome da regra" maxLength={80} value={name} onChange={(e) => setName(e.currentTarget.value)} />
            <Radio.Group label="Quando" value={kind} onChange={(v) => setKind(v as typeof kind)}>
              <Stack gap="xs" mt="xs">
                <Radio value="power_above" label="Uma tomada consome demasiado durante algum tempo" />
                <Radio value="presence_changed" label="Alguém entra ou sai de casa" />
              </Stack>
            </Radio.Group>
            {power && (
              <>
                <Select label="Tomada a vigiar" data={plugs} value={meter} onChange={setMeter} placeholder="Escolhe uma tomada" />
                <NumberInput label="Potência acima de (W)" min={1} allowDecimal={false} value={watts} onChange={setWatts} />
                <NumberInput label="Durante (minutos)" min={0} max={1440} allowDecimal={false} value={minutes} onChange={setMinutes} />
              </>
            )}
            <Select label="Desliga a tomada" data={plugs} value={target} onChange={setTarget} placeholder="Escolhe uma tomada" />
            <Alert color="yellow" icon={<IconInfoCircle />}>A tomada pode ser a extensão que alimenta vários aparelhos: desligá-la corta tudo o que lá está.</Alert>
            <Button w="fit-content" disabled={!valid} loading={busy} onClick={() => void submit()}>Propor à casa</Button>
          </>
        )}
      </Stack>
    </Card>
  );
}
