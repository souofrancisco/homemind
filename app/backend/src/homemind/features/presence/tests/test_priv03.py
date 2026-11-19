"""PRIV-03: compactação dos brutos, eliminação ao revogar/sair, exportação própria e provas de que
nada financeiro, o replay nem a idempotência do barramento se perdem. Relógio simulado, sem rede."""

import asyncio
import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import replace, stable_id
from homemind.contracts.presence import (
    DoorCrossed,
    DoorDirection,
    PersonPresence,
    PresenceConfirmationRequest,
    PresenceEvent,
    PresenceSource,
    PresenceState,
    UncertainReason,
)
from homemind.core.config import Settings
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, append_event, load_events, replay
from homemind.features.households.tests.conftest import HOUSE_B, NOW, seed_two_houses
from homemind.features.presence import retention as rt
from homemind.features.presence.tests.conftest import A, as_
from homemind.features.retention.policy import EVENT_CATEGORY, Category

SIM = fx.SIM_INFERRED
H = fx.HOUSEHOLD
BRUNO, ANA = fx.BRUNO, fx.ANA


LISBON = ZoneInfo("Europe/Lisbon")


def at(day: date, hh: int = 0, mm: int = 0) -> datetime:
    """Hora LOCAL da casa (Europa/Lisboa) em UTC: em outubro é UTC+1."""
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=LISBON).astimezone(UTC)


D = date(2026, 10, 1)  # 47 dias antes de NOW: compactado com N = 30
RECENT = NOW - timedelta(hours=30)  # lido pela fusão: nunca se apaga


def _eid(*parts) -> object:
    return stable_id("priv03", *map(str, parts))


def cue(rid, ts, source=PresenceSource.wifi, state=PresenceState.home, n=0, house=H):
    extra = {}
    if source is PresenceSource.appliance:
        extra["consumption_event_id"] = _eid("consumption", n)
    data = PresenceEvent(
        id=_eid("cue-data", rid, ts, n), household_id=house, resident_id=rid, ts=ts, state=state,
        source=source, confidence=0.8, provenance=SIM, **extra,
    )  # fmt: skip
    return de.PresenceCueRecorded(
        id=_eid("cue", rid, ts, n), ts=ts, household_id=house, provenance=SIM, data=data
    )


def changed(rid, ts, state, reason=None, house=H):
    data = PersonPresence(
        resident_id=rid, state=state, since=ts, confidence=0.8, provenance=SIM,
        sources=[PresenceSource.wifi], reason=reason,
    )  # fmt: skip
    return de.PresenceChanged(
        id=_eid("changed", rid, ts), ts=ts, household_id=house, provenance=SIM, data=data
    )


def ask(rid, ts, house=H):
    data = PresenceConfirmationRequest(
        id=_eid("ask", rid, ts), resident_id=rid, reason=UncertainReason.no_recent_cues,
        expires_at=ts + timedelta(minutes=30),
    )  # fmt: skip
    return de.PresenceConfirmationNeeded(
        id=_eid("askev", rid, ts), ts=ts, household_id=house, provenance=SIM, data=data
    )


def door(ts, direction=DoorDirection.entered, house=H):
    data = DoorCrossed(ts=ts, direction=direction, confidence=0.9, provenance=SIM)
    return de.PresenceDoorCrossed(
        id=_eid("door", ts, direction), ts=ts, household_id=house, provenance=SIM, data=data
    )


def financial(ts, name):
    c = replace(fx.consumption(closed=True), id=stable_id("consumption", name))
    return de.EnergyConsumptionClosed(
        id=_eid("fin", name), ts=ts, household_id=H, provenance=c.provenance, data=c
    )


@pytest.fixture
def db():
    database = Database(":memory:")
    database.open()
    migrate(database)

    def seed(conn):
        seed_two_houses(conn)
        conn.execute(
            "UPDATE membership SET presence_opt_in = 1 WHERE resident_id IN (?, ?)",
            (str(BRUNO), str(ANA)),
        )

    database.run_sync(seed)
    yield database
    database.close()


def put(db, *events):
    db.run_sync(lambda c: [append_event(c, e) for e in events])


def q(db, sql, *args):
    return db.run_sync(lambda c: [tuple(r) for r in c.execute(sql, args).fetchall()])


def raw_types(db):
    return [r[0] for r in q(db, "SELECT type FROM domain_event WHERE type LIKE 'presence.%'")]


def seed_mixed(db):
    """Dia D com tudo o que a presença produz + eventos recentes + dados financeiros."""
    put(
        db,
        changed(BRUNO, at(D, 8), PresenceState.home),
        changed(BRUNO, at(D, 18), PresenceState.away),
        changed(BRUNO, at(D, 22), PresenceState.uncertain, UncertainReason.no_recent_cues),
        cue(BRUNO, at(D, 8, 1)),
        cue(BRUNO, at(D, 9), PresenceSource.wifi, n=2),
        cue(BRUNO, at(D, 19), PresenceSource.manual, PresenceState.away),
        cue(BRUNO, at(D, 10), PresenceSource.appliance, n=1),
        ask(BRUNO, at(D, 21)),
        changed(ANA, at(D, 12), PresenceState.home),
        door(at(D, 8), DoorDirection.entered),
        door(at(D, 9), DoorDirection.entered),
        door(at(D, 18), DoorDirection.left),
        # recentes: dentro da janela da fusão (48 h) e da ocupação (24 h)
        cue(BRUNO, RECENT),
        door(NOW - timedelta(hours=3)),
        changed(BRUNO, NOW - timedelta(hours=2), PresenceState.home),
        # financeiros (antigos e recentes): intocáveis
        financial(at(D, 12), "velho"),
        financial(NOW - timedelta(hours=1), "novo"),
    )
    db.run_sync(
        lambda c: c.executemany(
            "INSERT INTO processed_event VALUES (?,?,?)",
            [
                ("presence.fusion", str(_eid("cue", BRUNO, at(D, 8, 1), 0)), NOW.isoformat()),
                ("billing.x", str(_eid("fin", "velho")), NOW.isoformat()),
                ("presence.fusion", str(_eid("cue", BRUNO, RECENT, 0)), NOW.isoformat()),
            ],
        )
    )


def set_opt_in(db, rid, value, house=None):
    sql = "UPDATE membership SET presence_opt_in = ? WHERE resident_id = ?"
    args = [value, str(rid)]
    if house:
        sql, args = sql + " AND household_id = ?", [*args, str(house)]
    db.run_sync(lambda c: c.execute(sql, args))


def aggregates(db):
    return (
        q(db, "SELECT * FROM presence_daily ORDER BY 1,2,3"),
        q(db, "SELECT * FROM presence_door_daily"),
        q(db, "SELECT COUNT(*) FROM domain_event"),
    )


def financial_snapshot(db):
    return (
        q(
            db,
            "SELECT id, type, payload_json FROM domain_event WHERE type NOT LIKE 'presence.%'"
            " ORDER BY seq",
        ),
        q(
            db,
            "SELECT consumer, event_id FROM processed_event WHERE consumer NOT LIKE 'presence.%'",
        ),
    )


# --- política ----------------------------------------------------------------------------------


def test_prazo_configuravel_30_por_omissao_e_nunca_abaixo_das_janelas_de_leitura():
    assert Settings().presence_retention_days == 30
    assert Settings(presence_retention_days=0).presence_retention_days == 0
    with pytest.raises(ValueError, match="pelo menos 2"):
        Settings(presence_retention_days=1)
    assert rt.MIN_DAYS * 24 >= 48  # a fusão lê 48 h


def test_os_tipos_de_presenca_da_politica_sao_os_que_se_podem_apagar():
    cats = {t for t, c in EVENT_CATEGORY.items() if c is Category.presence}
    assert cats == set(rt.PRESENCE_EVENT_TYPES)


def test_so_a_presenca_e_apagavel_o_resto_continua_imutavel(db):
    seed_mixed(db)
    for typ in ("energy.consumption_closed",):
        with pytest.raises(sqlite3.IntegrityError, match="imutável"):
            db.run_sync(
                lambda c, typ=typ: c.execute("DELETE FROM domain_event WHERE type = ?", (typ,))
            )
    with pytest.raises(sqlite3.IntegrityError, match="imutável"):
        db.run_sync(lambda c: c.execute("UPDATE domain_event SET ts = ts"))  # nunca UPDATE
    db.run_sync(
        lambda c: c.execute("DELETE FROM domain_event WHERE type = 'presence.door_crossed'")
    )


# --- compactação -------------------------------------------------------------------------------


def test_compacta_em_agregados_sem_horarios_e_apaga_so_os_brutos_antigos(db):
    seed_mixed(db)
    before_fin = financial_snapshot(db)
    done = rt.compact(db.run_sync, NOW, 30)

    # só ficam os recentes (janelas da fusão e da ocupação intactas)
    left = q(db, "SELECT type, ts FROM domain_event WHERE type LIKE 'presence.%' ORDER BY seq")
    assert sorted(t for t, _ in left) == ["presence.changed", "presence.cue_recorded",
                                          "presence.door_crossed"]  # fmt: skip
    assert all(datetime.fromisoformat(ts) >= NOW - timedelta(hours=48) for _, ts in left)
    assert done.events == 12 and done.days >= 17

    row = q(
        db,
        "SELECT * FROM presence_daily WHERE resident_id = ? AND day = ?",
        str(BRUNO),
        D.isoformat(),
    )[0]
    cols = [c[1] for c in q(db, "PRAGMA table_info(presence_daily)")]
    r = dict(zip(cols, row, strict=True))
    # incerto 0-8 h, em casa 8-18, fora 18-22, incerto 22-24 (carry: sem estado conhecido)
    assert (r["seconds_in"], r["seconds_out"], r["seconds_uncertain"]) == (
        36000,
        14400,
        28800 + 7200,
    )
    assert r["end_state"] == "uncertain"
    assert (r["cues_wifi"], r["cues_manual"], r["cues_appliance"], r["confirmation_requests"]) == (
        2, 1, 1, 1,
    )  # fmt: skip
    # Ana: «em casa» desde as 12 h
    ana = q(db, "SELECT seconds_in, seconds_uncertain FROM presence_daily"
            " WHERE resident_id = ? AND day = ?", str(ANA), D.isoformat())[0]  # fmt: skip
    assert ana == (12 * 3600, 12 * 3600)
    # o estado transita para os dias seguintes (sem eventos): continuidade, sem horas
    nxt = q(db, "SELECT seconds_uncertain, end_state FROM presence_daily WHERE resident_id = ?"
            " AND day = ?", str(BRUNO), (D + timedelta(days=1)).isoformat())[0]  # fmt: skip
    assert nxt == (86400, "uncertain")
    # porta: por casa e dia, só contagens
    assert q(db, "SELECT day, entered, left FROM presence_door_daily") == [(D.isoformat(), 2, 1)]
    # nenhum horário nem identificador de rede nos agregados
    dump = json.dumps(
        q(db, "SELECT * FROM presence_daily") + q(db, "SELECT * FROM presence_door_daily")
    )
    assert not re.search(r"\d{2}:\d{2}", dump) and "T" not in re.sub(r"[^A-Za-z]", "", dump)
    # dias recentes ainda não compactados
    assert q(db, "SELECT COUNT(*) FROM presence_daily WHERE day >= '2026-10-18'") == [(0,)]
    # auditoria: contagens, sem conteúdo
    log = q(db, "SELECT action, household_id, resident_id, counts_json FROM presence_retention_log")
    assert (
        log[0][0] == "compact"
        and "events" in log[0][3]
        and "T" not in log[0][3].replace("aggregate_rows", "")
    )
    # nada financeiro tocado
    assert financial_snapshot(db) == before_fin


def test_marcas_dos_consumidores_saem_com_os_brutos_e_as_dos_recentes_ficam(db):
    seed_mixed(db)
    rt.compact(db.run_sync, NOW, 30)
    marks = q(db, "SELECT consumer, event_id FROM processed_event ORDER BY event_id")
    assert {c for c, _ in marks} == {"presence.fusion", "billing.x"}
    assert ("presence.fusion", str(_eid("cue", BRUNO, at(D, 8, 1), 0))) not in marks
    assert ("presence.fusion", str(_eid("cue", BRUNO, RECENT, 0))) in marks
    assert q(db, "PRAGMA foreign_key_check") == []


def test_repetir_nao_muda_nada_e_nao_conta_a_dobrar(db):
    seed_mixed(db)
    rt.compact(db.run_sync, NOW, 30)
    snap = aggregates(db)
    assert not rt.compact(db.run_sync, NOW, 30)
    assert aggregates(db) == snap


def test_prazo_nunca_abaixo_de_48_horas_e_zero_desliga(db):
    old = NOW - timedelta(hours=64)  # 14/11 20:00: dia inteiro já passado
    put(db, cue(BRUNO, old), cue(BRUNO, NOW - timedelta(hours=49), n=1),
        cue(BRUNO, NOW - timedelta(hours=30), n=2), door(NOW - timedelta(hours=23)))  # fmt: skip
    assert not rt.compact(db.run_sync, NOW, 0)
    assert len(raw_types(db)) == 4
    rt.compact(db.run_sync, NOW, 1)  # pede 1 dia: o mínimo é 2 dias inteiros
    left = [datetime.fromisoformat(t) for (t,) in q(db, "SELECT ts FROM domain_event")]
    assert len(left) == 3 and old not in left  # só o de há 64 h; tudo o que a fusão lê fica
    assert all(t >= NOW - timedelta(hours=48) or t == NOW - timedelta(hours=49) for t in left)


def test_evento_que_um_consumidor_ainda_tenta_nao_se_apaga(db):
    seed_mixed(db)
    victim = str(_eid("cue", BRUNO, at(D, 8, 1), 0))
    db.run_sync(
        lambda c: c.execute(
            "INSERT INTO event_failure VALUES ('presence.fusion', ?, 2, 'ValueError', 0, ?)",
            (victim, NOW.isoformat()),
        )
    )
    rt.compact(db.run_sync, NOW, 30)
    assert q(db, "SELECT COUNT(*) FROM domain_event WHERE id = ?", victim) == [(1,)]


def test_falha_a_meio_do_dia_nao_perde_nem_duplica(db, monkeypatch):
    seed_mixed(db)

    def boom(*a, **k):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(rt, "_delete_events", boom)
    with pytest.raises(RuntimeError):
        rt.compact(db.run_sync, NOW, 30)
    assert q(db, "SELECT COUNT(*) FROM presence_daily") == [(0,)]  # transação revertida
    assert len(raw_types(db)) == 15
    monkeypatch.undo()
    rt.compact(db.run_sync, NOW, 30)
    assert q(db, "SELECT SUM(cues_wifi) FROM presence_daily") == [(2,)]


def test_morador_sem_opt_in_nao_gera_agregado(db):
    put(db, cue(fx.CARLA, at(D, 9)), changed(fx.CARLA, at(D, 9), PresenceState.home))
    rt.compact(db.run_sync, NOW, 30)
    assert q(db, "SELECT COUNT(*) FROM presence_daily") == [(0,)]
    assert raw_types(db) == []  # apaga-se sem agregar


def test_pedidos_de_confirmacao_antigos_saem(db):
    def ins(conn):
        for name, at_ in (("velho", at(D, 21)), ("novo", NOW - timedelta(hours=1))):
            conn.execute(
                "INSERT INTO presence_confirmation (id, household_id, resident_id, reason,"
                " created_at, expires_at) VALUES (?,?,?,?,?,?)",
                (str(_eid(name)), str(H), str(BRUNO), "no_recent_cues", at_.isoformat(),
                 (at_ + timedelta(minutes=30)).isoformat()),
            )  # fmt: skip

    db.run_sync(ins)
    assert rt.compact(db.run_sync, NOW, 30).confirmations == 1
    assert q(db, "SELECT id FROM presence_confirmation") == [(str(_eid("novo")),)]


# --- replay e idempotência -----------------------------------------------------------------------


def test_replay_e_idempotencia_do_barramento_depois_de_compactar(db):
    seed_mixed(db)
    rt.compact(db.run_sync, NOW, 30)
    seen: list[str] = []
    bus = EventBus(db)
    bus.subscribe("presence.fusion", lambda conn, s: seen.append(s.event.type) or None,
                  types=["presence.cue_recorded", "presence.door_crossed"])  # fmt: skip

    async def go():
        stored = db.run_sync(lambda c: load_events(c, types=["presence.cue_recorded"]))
        assert stored
        # já processado antes da compactação: não repete o efeito
        assert [await bus.deliver("presence.fusion", s) for s in stored] == [False]
        # republicar o que ficou noutra base: sem duplicados
        other = Database(":memory:")
        other.open()
        migrate(other)
        other.run_sync(seed_two_houses)
        events = db.run_sync(lambda c: load_events(c))
        again = await replay(events, EventBus(other))
        again2 = await replay(events, EventBus(other))
        assert [s.event.id for s in again] == [s.event.id for s in again2]
        assert q(other, "SELECT COUNT(*) FROM domain_event") == [(len(events),)]
        other.close()

    asyncio.run(go())
    assert seen == []


# --- eliminação ao revogar ou sair -----------------------------------


def seed_person_data(db):
    seed_mixed(db)
    db.run_sync(
        lambda c: (
            c.execute(
                "INSERT INTO presence_state (household_id, resident_id, state, since, confidence,"
                " origin, kind, sources_json, reason, updated_at)"
                " VALUES (?,?,'in',?,0.8,'simulated','inferred','[]',NULL,?)",
                (str(H), str(BRUNO), NOW.isoformat(), NOW.isoformat()),
            ),
            c.execute(
                "INSERT INTO presence_device (id, household_id, resident_id, label, match_key,"
                " wifi_opt_in, consented_at, created_at) VALUES (?,?,?,?,?,1,?,?)",
                (
                    str(_eid("dev")),
                    str(H),
                    str(BRUNO),
                    "Telemóvel",
                    "k" * 32,
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            ),  # fmt: skip
        )
    )
    rt.compact(db.run_sync, NOW, 30)  # cria também agregados do Bruno e da Ana


def bruno_rows(db):
    return [
        q(db, "SELECT COUNT(*) FROM presence_state WHERE resident_id = ?", str(BRUNO))[0][0],
        q(db, "SELECT COUNT(*) FROM presence_device WHERE resident_id = ?", str(BRUNO))[0][0],
        q(db, "SELECT COUNT(*) FROM presence_daily WHERE resident_id = ?", str(BRUNO))[0][0],
        q(db, "SELECT COUNT(*) FROM domain_event WHERE type IN"
              " ('presence.cue_recorded','presence.changed','presence.confirmation_needed')"
              " AND household_id = ? AND json_extract(payload_json, '$.resident_id') = ?",
          str(H), str(BRUNO))[0][0],
    ]  # fmt: skip


def test_com_opt_in_nada_se_elimina(db):
    seed_person_data(db)
    assert not rt.erase_unconsented(db.run_sync, NOW).residents
    assert all(bruno_rows(db))


def test_revogar_o_opt_in_elimina_o_que_e_do_morador_e_mais_nada(db):
    seed_person_data(db)
    ana_before = q(db, "SELECT * FROM presence_daily WHERE resident_id = ?", str(ANA))
    fin = financial_snapshot(db)
    doors = q(db, "SELECT * FROM presence_door_daily")
    other_house = [changed(BRUNO, RECENT, PresenceState.home, house=HOUSE_B)]
    put(db, *other_house)

    set_opt_in(db, BRUNO, 0, H)
    out = rt.erase_unconsented(db.run_sync, NOW)

    assert out.residents == 1 and bruno_rows(db) == [0, 0, 0, 0]
    assert q(db, "SELECT * FROM presence_daily WHERE resident_id = ?", str(ANA)) == ana_before
    assert q(db, "SELECT * FROM presence_door_daily") == doors  # anónimo: fica
    assert financial_snapshot(db) == fin  # nenhum evento financeiro nem marca de consumidor
    # a outra casa do mesmo morador (opt-in em vigor) não é tocada
    assert q(db, "SELECT COUNT(*) FROM domain_event WHERE household_id = ?"
             " AND type = 'presence.changed'", str(HOUSE_B)) == [(1,)]  # fmt: skip
    log = q(db, "SELECT action, resident_id, reason, counts_json FROM presence_retention_log"
            " WHERE action = 'erase'")  # fmt: skip
    assert log[0][:3] == ("erase", str(BRUNO), "opt_in_revoked")
    assert not rt.erase_unconsented(db.run_sync, NOW).residents  # idempotente
    assert q(db, "PRAGMA foreign_key_check") == []


def test_sair_da_casa_elimina_com_o_motivo_certo(db):
    seed_person_data(db)
    db.run_sync(lambda c: c.execute(
        "UPDATE membership SET status = 'ended', ends_on = '2026-11-10'"
        " WHERE resident_id = ? AND household_id = ?", (str(ANA), str(H))))  # fmt: skip
    assert rt.erase_unconsented(db.run_sync, NOW).residents == 1
    assert q(db, "SELECT COUNT(*) FROM presence_daily WHERE resident_id = ?", str(ANA)) == [(0,)]
    assert q(db, "SELECT reason FROM presence_retention_log WHERE resident_id = ?", str(ANA)) == [
        ("left_household",)
    ]  # fmt: skip
    assert all(bruno_rows(db))


def test_a_compactacao_nao_agrega_quem_revogou_entretanto(db):
    seed_mixed(db)  # ainda por compactar
    set_opt_in(db, ANA, 0)
    rt.compact(db.run_sync, NOW, 30)
    assert q(db, "SELECT COUNT(*) FROM presence_daily WHERE resident_id = ?", str(ANA)) == [(0,)]
    assert q(db, "SELECT COUNT(*) FROM presence_daily WHERE resident_id = ?", str(BRUNO))[0][0] > 0


# --- exportação ------------------------------------------------------------


def seed_http(client):
    db = client.app_state.db
    put(db, cue(BRUNO, RECENT), cue(ANA, RECENT, n=7), changed(ANA, RECENT, PresenceState.home),
        changed(BRUNO, RECENT, PresenceState.home), door(NOW - timedelta(hours=2)))  # fmt: skip
    db.run_sync(lambda c: c.execute(
        "INSERT INTO presence_device (id, household_id, resident_id, label, match_key, wifi_opt_in,"
        " consented_at, created_at) VALUES (?,?,?,?,?,1,?,?)",
        (str(_eid("devA")), A, str(ANA), "Telemóvel da Ana", "secreto-hash-ana-123456",
         NOW.isoformat(), NOW.isoformat())))  # fmt: skip
    set_opt_in(db, ANA, 1)


def test_exportacao_so_devolve_os_dados_de_quem_pede(client):
    seed_http(client)
    r = client.get(f"/api/presence/export?household_id={A}", headers=as_("sub-bruno"))
    assert r.status_code == 200
    body = r.json()
    assert body["presence_opt_in"] is True and body["household_id"] == A
    assert len(body["cues"]) == 1 and len(body["changes"]) == 1
    assert body["retention"] == {"raw_days": 30, "proposal": True}
    text = r.text
    assert str(ANA) not in text and "Ana" not in text and "secreto-hash" not in text
    assert "match_key" not in text and "door" not in text
    # a Ana vê os seus, não os do Bruno
    ana = client.get(f"/api/presence/export?household_id={A}", headers=as_("sub-ana")).json()
    assert [d["label"] for d in ana["devices"]] == ["Telemóvel da Ana"]
    assert str(BRUNO) not in json.dumps(ana)


@pytest.mark.parametrize("sub", ["sub-senhorio", "sub-operador"])
def test_exportacao_senhorio_e_operador_403(client, sub):
    r = client.get(f"/api/presence/export?household_id={A}", headers=as_(sub))
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"


def test_exportacao_estranhos_e_anonimos(client):
    seed_http(client)
    assert (
        client.get(f"/api/presence/export?household_id={A}", headers=as_("sub-eva")).status_code
        == 404
    )
    assert client.get(f"/api/presence/export?household_id={A}").status_code == 401
    assert client.get("/api/presence/export", headers=as_("sub-bruno")).status_code == 400


def test_exportacao_cross_account_a_casa_b_nao_mostra_a_casa_a(client):
    """Bruno está nas duas casas: cada exportação só tem os dados da casa pedida."""
    seed_http(client)
    put(client.app_state.db, changed(BRUNO, RECENT + timedelta(minutes=5), PresenceState.away,
                                     house=HOUSE_B))  # fmt: skip
    b = client.get(f"/api/presence/export?household_id={HOUSE_B}", headers=as_("sub-bruno")).json()
    assert [c["state"] for c in b["changes"]] == ["out"] and b["cues"] == []
    a = client.get(f"/api/presence/export?household_id={A}", headers=as_("sub-bruno")).json()
    assert [c["state"] for c in a["changes"]] == ["in"]
    # um morador da casa B não exporta a casa A
    assert (
        client.get(f"/api/presence/export?household_id={A}", headers=as_("sub-hugo")).status_code
        == 404
    )


def test_exportacao_depois_de_revogar_ja_nao_tem_dados(client):
    seed_http(client)
    db = client.app_state.db
    set_opt_in(db, BRUNO, 0)
    rt.erase_unconsented(db.run_sync, NOW)
    body = client.get(f"/api/presence/export?household_id={A}", headers=as_("sub-bruno")).json()
    assert body["presence_opt_in"] is False
    assert body["cues"] == body["changes"] == body["daily"] == body["devices"] == []
    assert body["current_state"] is None
