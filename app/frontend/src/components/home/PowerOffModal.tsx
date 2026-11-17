import { Alert, Button, Group, Modal, Stack, Text } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { usePowerOff } from "../../hooks/usePowerOff";

export default function PowerOffModal({ opened, onClose, simulated }: { opened: boolean; onClose: () => void; simulated: boolean }) {
  const { busy, run } = usePowerOff();
  return <Modal opened={opened} onClose={onClose} title="Desligar tudo?" centered>
    <Stack><Alert color="orange" icon={<IconAlertCircle />}>{simulated ? "Esta ação é uma demonstração e não altera dispositivos físicos." : "O pedido será enviado à casa. Só será apresentado como concluído após confirmação."}</Alert><Text>Confirma que quer desligar os dispositivos controlados?</Text><Group justify="flex-end"><Button variant="default" onClick={onClose}>Cancelar</Button><Button color="red" loading={busy} onClick={() => void run().then((ok) => ok && onClose())}>Confirmar</Button></Group></Stack>
  </Modal>;
}
