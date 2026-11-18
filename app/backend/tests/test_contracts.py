from datetime import UTC, datetime

from homemind.contracts.eventos import Presenca, evento_adapter

HORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def test_evento_presenca_ida_e_volta_json_pelo_discriminador():
    evento = Presenca(ha_alguem=False, hora=HORA)
    assert evento_adapter.validate_json(evento.model_dump_json()) == evento
