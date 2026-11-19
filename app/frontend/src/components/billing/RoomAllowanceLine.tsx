import { Button, Group, NumberInput, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { setRoomAllowance, type RoomAllowanceView } from "../../services/billing/allowances";

// Plafond solidário de um quarto (BILL-03). O servidor decide quando a mudança vale (dia 1 do mês
// seguinte); aqui só se mostra e, para o senhorio, se agenda.
const day = (iso: string) => new Intl.DateTimeFormat("pt-PT", { dateStyle: "long" }).format(new Date(`${iso}T12:00:00`));
const kwh = (wh: number) => (wh / 1000).toLocaleString("pt-PT", { maximumFractionDigits: 1 });

export default function RoomAllowanceLine({ householdId, view, canEdit, onChange }: {
  householdId: string; view: RoomAllowanceView; canEdit: boolean; onChange: (v: RoomAllowanceView) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState<number | string>(view.current_wh / 1000);
  const [busy, setBusy] = useState(false);
  const save = () => {
    setBusy(true);
    setRoomAllowance(householdId, view.room_id, Math.round(Number(value) * 1000))
      .then((v) => { onChange(v); setEditing(false); })
      .catch(() => undefined)
      .finally(() => setBusy(false));
  };
  return (
    <Stack gap={4}>
      {view.upcoming_from && view.upcoming_wh != null && (
        <Text size="xs" c="blue">A partir de {day(view.upcoming_from)}: {view.upcoming_wh ? `${kwh(view.upcoming_wh)} kWh/mês` : "sem plafond"}</Text>
      )}
      {canEdit && !editing && <Button size="compact-xs" variant="subtle" w="fit-content" onClick={() => setEditing(true)}>Mudar plafond</Button>}
      {canEdit && editing && (
        <Stack gap={4}>
          <Group gap="xs" align="flex-end" wrap="nowrap">
            <NumberInput size="xs" label="kWh por mês (0 = sem plafond)" min={0} decimalScale={1} value={value} onChange={setValue} w={170} />
            <Button size="xs" loading={busy} disabled={value === "" || Number(value) < 0} onClick={save}>Agendar</Button>
            <Button size="xs" variant="subtle" onClick={() => setEditing(false)}>Cancelar</Button>
          </Group>
          <Text size="xs" c="dimmed">Vale a partir do mês seguinte; o mês em curso e as faturas fechadas não mudam.</Text>
        </Stack>
      )}
    </Stack>
  );
}
