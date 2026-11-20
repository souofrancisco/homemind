import { Alert, Button, Card, NumberInput, Radio, SegmentedControl, Select, Stack, Text, TextInput, Title } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";
import type { AutomationProposeIn } from "../../services/automations/api";

export type PlugOption = { value: string; label: string; personalAllowed: boolean };

type Props = { plugs: PlugOption[]; busy: boolean; simulated: boolean; onSubmit: (body: AutomationProposeIn) => Promise<boolean> };

export default function ProposeRuleForm({ plugs, busy, simulated, onSubmit }: Props) {
  const [scope, setScope] = useState<"personal" | "house">("personal");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"power_above" | "presence_changed">("power_above");
  const [watts, setWatts] = useState<number | string>("");
  const [minutes, setMinutes] = useState<number | string>("");
  const [meter, setMeter] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);

  const personal = scope === "personal";
  const options = personal ? plugs.filter((p) => p.personalAllowed) : plugs;
  const power = kind === "power_above";
  const valid = name.trim() !== "" && target != null && (!power || (meter != null && Number(watts) > 0 && Number(watts) <= 100000 && minutes !== "" && Number(minutes) >= 0));
  const submit = async () => {
    const trigger = power
      ? { kind, device_id: meter, threshold_w: Number(watts), duration_s: Math.round(Number(minutes) * 60) }
      : { kind };
    if (await onSubmit({ name: name.trim(), trigger, target_device_id: target!, scope })) {
      setName(""); setWatts(""); setMinutes(""); setMeter(null); setTarget(null);
    }
  };
  const changeScope = (v: string) => { setScope(v as typeof scope); setMeter(null); setTarget(null); };
  return (
    <Card withBorder radius="lg" p="lg">
      <Stack gap="md">
        <Title order={3} size="h4">Nova regra</Title>
        <SegmentedControl fullWidth value={scope} onChange={changeScope} aria-label="Para quem é a regra" data={[
          { value: "personal", label: "Só para mim" },
          { value: "house", label: "Para a casa toda" },
        ]} />
        <Text size="sm" c="dimmed">
          {personal
            ? "A regra só desliga uma tomada do teu quarto. Fica ativa logo, só tu a vês e só tu a podes suspender."
            : "A regra só desliga uma tomada. Só fica ativa se todos os moradores votarem a favor em 24 h."}
          {simulated ? " Nesta casa de demonstração a execução é SIMULADA." : ""}
        </Text>
        {!plugs.length ? <Alert icon={<IconInfoCircle />} color="gray">Ainda não há tomadas conhecidas nesta casa, por isso não é possível criar regras.</Alert>
          : !options.length ? <Alert icon={<IconInfoCircle />} color="gray">Não há tomadas no teu quarto. Podes criar uma regra para a casa toda, ou pedir ao senhorio que associe uma tomada ao teu quarto.</Alert> : (
          <>
            <TextInput label="Nome da regra" maxLength={80} value={name} onChange={(e) => setName(e.currentTarget.value)} />
            <Radio.Group label="Quando" value={kind} onChange={(v) => setKind(v as typeof kind)}>
              <Stack gap="xs" mt="xs">
                <Radio value="power_above" label="Uma tomada consome demasiado durante algum tempo" />
                <Radio value="presence_changed" label={personal ? "Eu entro ou saio de casa" : "Alguém entra ou sai de casa"} />
              </Stack>
            </Radio.Group>
            {power && (
              <>
                <Select label="Tomada a vigiar" data={options} value={meter} onChange={setMeter} placeholder="Escolhe uma tomada" />
                <NumberInput label="Potência acima de (W)" min={1} max={100000} allowDecimal={false} value={watts} onChange={setWatts} />
                <NumberInput label="Durante (minutos)" min={0} max={1440} allowDecimal={false} value={minutes} onChange={setMinutes} />
              </>
            )}
            <Select label="Desliga a tomada" data={options} value={target} onChange={setTarget} placeholder="Escolhe uma tomada" />
            <Alert color="yellow" icon={<IconInfoCircle />}>A tomada pode ser a extensão que alimenta vários aparelhos: desligá-la corta tudo o que lá está.</Alert>
            <Button w="fit-content" mih={44} disabled={!valid} loading={busy} onClick={() => void submit()}>{personal ? "Criar regra" : "Propor à casa"}</Button>
          </>
        )}
      </Stack>
    </Card>
  );
}
