"""PRIV-03: medição de volume. UM ANO SIMULADO de presença de uma casa de 4 moradores, antes e
depois da compactação (base em ficheiro, relógio simulado, sem rede).

Lento (alguns segundos) e só mede: corre com `PRESENCE_VOLUME=1 uv run pytest -q -s -k volume`
(desde `app/backend`). Sem a variável fica de fora do `make test`. Os números impressos são os
que `docs/modules/presence.md` cita; dependem da carga simulada abaixo, que é uma SUPOSIÇÃO
(não há dados reais): por morador e dia ~14 pistas Wi-Fi, 4 de aparelho, 2 manuais, 6 mudanças de
estado e 0,5 pedidos de confirmação; por casa e dia ~24 passagens na porta e ~30 mudanças de
ocupação.
"""

import os
import random
import statistics
import time
from datetime import timedelta

import pytest

from homemind.contracts import domain_events as de
from homemind.contracts import fixtures as fx
from homemind.contracts.common import stable_id
from homemind.contracts.presence import (
    DoorDirection,
    HouseOccupancy,
    OccupancyState,
    PresenceSource,
    PresenceState,
)
from homemind.core.db import Database, migrate
from homemind.core.events import EventBus, append_event
from homemind.features.households.tests.conftest import NOW, seed_two_houses
from homemind.features.presence import retention as rt
from homemind.features.presence.service import PresenceService
from homemind.features.presence.tests.test_priv03 import (
    ask,
    changed,
    cue,
    door,
    financial,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("PRESENCE_VOLUME") != "1", reason="medição lenta: PRESENCE_VOLUME=1"
)

H = fx.HOUSEHOLD
RESIDENTS = (fx.ANA, fx.BRUNO, fx.CARLA, fx.DIOGO)
DAYS = 365
MANUAL, APPLIANCE = PresenceSource.manual, PresenceSource.appliance


def generate(db: Database) -> int:
    rnd = random.Random(2026)

    def minute(day0):
        return day0 + timedelta(minutes=rnd.randrange(1440))

    def work(conn):
        n = 0
        for d in range(DAYS, 0, -1):
            day0 = NOW - timedelta(days=d)
            events = []
            for i, rid in enumerate(RESIDENTS):
                events += [cue(rid, minute(day0), n=d * 100 + k) for k in range(14)]
                events += [cue(rid, minute(day0), APPLIANCE, n=d * 100 + 20 + k) for k in range(4)]
                events += [
                    cue(rid, minute(day0), MANUAL, PresenceState.home, n=d * 100 + 40 + k)
                    for k in range(2)
                ]
                for k, st in enumerate([PresenceState.home, PresenceState.away] * 3):
                    events.append(changed(rid, day0 + timedelta(hours=3 * k + i, minutes=k), st))
                if d % 2:
                    events.append(ask(rid, day0 + timedelta(hours=20, minutes=i)))
            for k in range(24):
                direction = DoorDirection.entered if k % 2 == 0 else DoorDirection.left
                events.append(door(day0 + timedelta(minutes=30 * k + 1), direction))
            for k in range(30):
                ts = day0 + timedelta(minutes=47 * k)
                occ = HouseOccupancy(
                    ts=ts, state=OccupancyState.occupied, people_inside=2, visitors=0,
                    residents_home=2, provenance=fx.SIM_INFERRED,
                )  # fmt: skip
                events.append(
                    de.PresenceOccupancyChanged(
                        id=stable_id("volume-occ", str(d), str(k)),
                        ts=ts,
                        household_id=H,
                        provenance=fx.SIM_INFERRED,
                        data=occ,
                    )  # fmt: skip
                )
            if d % 30 == 0:  # alguns consumos financeiros: nunca se tocam
                events.append(financial(day0, f"mes-{d}"))
            for e in events:
                append_event(conn, e)
            n += len(events)
        return n

    return db.run_sync(work)


def scalar(db: Database, sql: str, *args) -> int:
    return db.run_sync(lambda c: c.execute(sql, args).fetchone()[0])


def size_mb(db: Database) -> float:
    pages, page = scalar(db, "PRAGMA page_count"), scalar(db, "PRAGMA page_size")
    return pages * page / 1e6


def fusion_ms(service: PresenceService, db: Database, runs: int = 30) -> float:
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        db.run_sync(lambda c: service.compute(c, H, fx.BRUNO, NOW))
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


def test_um_ano_de_presenca_antes_e_depois_da_compactacao(tmp_path):
    db = Database(tmp_path / "volume.sqlite3")
    db.open()
    migrate(db)

    def seed(conn):
        seed_two_houses(conn)
        conn.execute("UPDATE membership SET presence_opt_in = 1 WHERE role = 'tenant'")

    db.run_sync(seed)
    t = time.perf_counter()
    n = generate(db)
    print(f"\n[volume] gerados {n} eventos em {time.perf_counter() - t:.1f} s")
    service = PresenceService(db, EventBus(db), salt="x" * 16, clock=lambda: NOW)
    fin_sql = "SELECT COUNT(*) FROM domain_event WHERE type = 'energy.consumption_closed'"
    raw_sql = "SELECT COUNT(*) FROM domain_event WHERE type LIKE 'presence.%'"
    fin = scalar(db, fin_sql)

    raw_before, size_before = scalar(db, raw_sql), size_mb(db)
    f_before = fusion_ms(service, db)
    t = time.perf_counter()
    sweep = rt.erase_unconsented(db.run_sync, NOW)
    sweep_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    done = rt.compact(db.run_sync, NOW, 30)
    compact_s = time.perf_counter() - t
    raw_after, size_free = scalar(db, raw_sql), size_mb(db)
    db._conn.execute("VACUUM")  # liberta as páginas para medir o tamanho real
    size_after = size_mb(db)
    f_after = fusion_ms(service, db)
    t = time.perf_counter()
    rt.erase_unconsented(db.run_sync, NOW)
    sweep_after_ms = (time.perf_counter() - t) * 1000
    daily = scalar(db, "SELECT COUNT(*) FROM presence_daily")
    print(
        f"[volume] eventos presence.* antes={raw_before} depois={raw_after}; "
        f"agregados diários={daily}; apagados={done.events}\n"
        f"[volume] base antes={size_before:.1f} MB; depois (sem VACUUM)={size_free:.1f} MB; "
        f"depois (VACUUM)={size_after:.1f} MB\n"
        f"[volume] fusão (mediana de 30, 1 morador): antes={f_before:.1f} ms "
        f"depois={f_after:.1f} ms\n"
        f"[volume] compactação inicial={compact_s:.1f} s ({done.days} dias); "
        f"varrimento de eliminação antes={sweep_ms:.0f} ms depois={sweep_after_ms:.0f} ms"
    )
    assert sweep.residents == 0
    assert raw_after < raw_before / 5
    assert scalar(db, fin_sql) == fin  # nenhum evento financeiro tocado
    kept = scalar(
        db, raw_sql + " AND julianday(ts) >= julianday(?)", (NOW - timedelta(days=30)).isoformat()
    )
    # fica tudo o que tem menos de N dias, mais (no máximo) o resto do dia local do corte
    assert 0 <= raw_after - kept <= 200
    db.close()
