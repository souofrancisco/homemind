"""Consumidor do barramento que decide e grava a quem pertence cada consumo (BILL-02).

- `energy.consumption_detected/closed` → guarda a última versão do consumo e, se ainda não
  houver decisão, aplica `attribution.decide` com a regra da casa em vigor no dia em que o
  consumo começou (`rules.policy_on`, HOUSE-04): atribuição direta (quarto, conta comum) ou
  pedido «De quem é esta conta?» (`billing.confirmation_needed`).
- Regra C (BILL-07): `presence_rule.sole_occupant` com a cópia billing dos eventos de presença.
- `notification.responded` com a votação decidida (D-32) → atribuição por confirmação.
- `expire_pending` (chamado periodicamente e no fecho da fatura): pedidos sem decisão no
  prazo → conta comum, por todos.

Enquanto energy não localiza nem estima custo (ENERGY-05 #83, PLANEADO), billing completa a
sua cópia do consumo com o que é configuração, não inferência:
- localização `unknown` → a divisão configurada da tomada (`device.room_id`): tomada de quarto
  → `room` («o teu quarto é teu»: tudo o que passa pela tomada do quarto); tomada de zona
  comum → `common`. Sem divisão, tomada desconhecida ou contador geral → fica `unknown`.
  Uma localização dada por energy nunca é substituída.
- sem `cost_estimate` → energia × preço de referência da casa (ou o preço médio da última
  fatura fechada), só para decidir se vale a pena perguntar; sem preço não se pergunta.

Síncrono e determinístico (datas dos próprios eventos): reprocessar o histórico dá o mesmo
resultado, e os ids derivados tornam os eventos de seguimento idempotentes. Nada se apaga.
"""

import sqlite3
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from homemind.contracts import domain_events as de
from homemind.contracts.billing import (
    Attribution,
    AttributionMethod,
    AttributionStatus,
    AttributionTarget,
    supersede,
)
from homemind.contracts.common import (
    Audit,
    Provenance,
    ValueKind,
    cost_cents,
    replace,
    stable_id,
)
from homemind.contracts.energy import (
    ConsumptionEvent,
    ConsumptionStatus,
    CostEstimate,
    LocationKind,
)
from homemind.contracts.household import CommonAreaRule
from homemind.contracts.notification import ConfirmationVerdict, RefType
from homemind.features.billing import presence_rule, rules, tariff
from homemind.features.billing.attribution import SYSTEM, decide

# Nome PERMANENTE (chave de idempotência em `processed_event`): renomear reprocessa tudo.
CONSUMER = "billing.attributor"
EVENT_TYPES = (
    "energy.consumption_detected",
    "energy.consumption_closed",
    "notification.responded",
)


def handle(conn: sqlite3.Connection, stored: de.StoredEvent) -> list[de.DomainEvent]:
    ev = stored.event
    if isinstance(ev, de.EnergyConsumptionDetected | de.EnergyConsumptionClosed):
        return _on_consumption(conn, ev)
    if isinstance(ev, de.NotificationResponded):
        return _on_responded(conn, ev)
    return []


# --- consumos -----------------------------------------------------------------------------------


def _on_consumption(
    conn: sqlite3.Connection, ev: de.EnergyConsumptionDetected | de.EnergyConsumptionClosed
) -> list[de.DomainEvent]:
    consumption = _save_consumption(conn, locate(conn, ev.data), ev.ts)
    cid = str(consumption.id)
    if active_attribution(conn, consumption.id) is not None:
        return []
    if conn.execute(
        "SELECT 1 FROM billing_confirmation WHERE consumption_event_id = ?", (cid,)
    ).fetchone():
        return []  # já se perguntou: decide a votação (ou o prazo)
    tenants = active_tenants(conn, consumption.household_id, consumption.started_at)
    policy = rules.policy_on(
        conn,
        consumption.household_id,
        rules.local_day(conn, consumption.household_id, consumption.started_at),
    )
    sole = None
    if policy.common_area_rule is CommonAreaRule.presence:
        found = presence_rule.sole_occupant(
            conn,
            consumption.household_id,
            [r for r, _ in tenants],
            consumption.started_at,
            consumption.ended_at,
        )
        sole = (found.resident_id, found.confidence, found.simulated) if found else None
    decision = decide(
        with_cost_estimate(conn, consumption),
        policy,
        {room: r for r, room in tenants if room is not None},
        [r for r, _ in tenants],
        ev.ts,
        sole,
    )
    if decision.attribution is not None:
        return [_record(conn, decision.attribution, ev.correlation_id)]
    if decision.confirmation is not None:
        req = decision.confirmation
        conn.execute(
            "INSERT INTO billing_confirmation (consumption_event_id, household_id, expires_at,"
            " status, created_at) VALUES (?,?,?,'pending',?)",
            (cid, str(consumption.household_id), req.expires_at.isoformat(), ev.ts.isoformat()),
        )
        return [
            de.BillingConfirmationNeeded(
                id=stable_id("billing.confirmation_needed", cid),
                ts=ev.ts,
                household_id=consumption.household_id,
                correlation_id=ev.correlation_id,
                provenance=consumption.provenance,
                data=req,
            )
        ]
    return []


def locate(conn: sqlite3.Connection, c: ConsumptionEvent) -> ConsumptionEvent:
    """Localização `unknown` → divisão configurada da tomada (ver docstring do módulo)."""
    if c.location is not LocationKind.unknown:
        return c
    row = conn.execute(
        "SELECT d.role, d.room_id, r.kind FROM device d"
        " JOIN room r ON r.household_id = d.household_id AND r.id = d.room_id"
        " WHERE d.household_id = ? AND d.id = ?",
        (str(c.household_id), str(c.device_id)),
    ).fetchone()
    if row is None or row["role"] == "main_meter":
        return c
    kind = LocationKind.room if row["kind"] == "bedroom" else LocationKind.common
    return replace(c, location=kind, room_id=UUID(row["room_id"]))


def with_cost_estimate(conn: sqlite3.Connection, c: ConsumptionEvent) -> ConsumptionEvent:
    """Sem custo de energy: energia × preço de referência (só para a decisão; não se grava)."""
    if c.cost_estimate is not None or c.energy_wh is None:
        return c
    price = reference_price(conn, c.household_id)
    if price is None:
        return c
    estimate = CostEstimate(cents=cost_cents(c.energy_wh, price), price_millicents_per_kwh=price)
    return replace(c, cost_estimate=estimate)


def reference_price(conn: sqlite3.Connection, household_id: UUID) -> int | None:
    """Preço do tarifário de referência (ALERT-02); no bi-horário, o mais alto dos dois: na
    dúvida pergunta-se, nunca se deixa de perguntar por subestimar o custo."""
    rate = tariff.load(conn, household_id).tariff
    if rate is None:
        return None
    return max(rate.price_millicents_per_kwh, rate.offpeak_price_millicents_per_kwh or 0)


def _save_consumption(conn: sqlite3.Connection, c: ConsumptionEvent, ts: datetime):
    """Guarda a versão mais recente; um `ongoing` atrasado nunca substitui um fecho."""
    row = conn.execute(
        "SELECT status, json FROM billing_consumption WHERE id = ?", (str(c.id),)
    ).fetchone()
    if row is not None and row["status"] != "ongoing" and c.status is ConsumptionStatus.ongoing:
        return ConsumptionEvent.model_validate_json(row["json"])
    conn.execute(
        "INSERT INTO billing_consumption (id, household_id, status, started_at, energy_wh, json,"
        " updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
        " energy_wh=excluded.energy_wh, json=excluded.json, updated_at=excluded.updated_at",
        (
            str(c.id),
            str(c.household_id),
            c.status.value,
            c.started_at.isoformat(),
            c.energy_wh,
            c.model_dump_json(),
            ts.isoformat(),
        ),
    )
    return c


# --- votação e prazo ------------------------------------------------------------------------------


def _on_responded(conn: sqlite3.Connection, ev: de.NotificationResponded) -> list[de.DomainEvent]:
    ref, outcome = ev.data.ref, ev.data.outcome
    if ref is None or ref.type is not RefType.consumption_event or outcome is None:
        return []
    if not outcome.decided or not _pending(conn, ref.id):
        return []  # a votar ainda, ou chegou depois do prazo/da decisão
    consumption = load_consumption(conn, ref.id)
    resident = outcome.resident_id if outcome.verdict is not ConfirmationVerdict.everyone else None
    vote = ev.data.response
    attribution = Attribution(
        id=stable_id("attribution", str(ref.id), "confirmation"),
        household_id=consumption.household_id,
        consumption_event_id=consumption.id,
        target_type=AttributionTarget.common if resident is None else AttributionTarget.resident,
        target_resident_id=resident,
        method=AttributionMethod.confirmation,
        provenance=Provenance(origin=consumption.provenance.origin, kind=ValueKind.measured),
        decided_by=Audit(at=vote.responded_at, by_resident_id=vote.resident_id),
    )
    _close_confirmation(conn, ref.id, "resolved")
    return [_record(conn, attribution, ev.correlation_id)]


def expire_pending(conn: sqlite3.Connection, now: datetime) -> list[de.DomainEvent]:
    """Pedidos sem decisão até `expires_at` → conta comum, dividida por todos (D-32)."""
    rows = conn.execute(
        "SELECT consumption_event_id, expires_at FROM billing_confirmation"
        " WHERE status = 'pending' AND expires_at <= ? ORDER BY expires_at",
        (now.isoformat(),),
    ).fetchall()
    out = []
    for row in rows:
        consumption = load_consumption(conn, UUID(row["consumption_event_id"]))
        at = datetime.fromisoformat(row["expires_at"])
        attribution = Attribution(
            id=stable_id("attribution", str(consumption.id), "expired"),
            household_id=consumption.household_id,
            consumption_event_id=consumption.id,
            target_type=AttributionTarget.common,
            method=AttributionMethod.equal_fallback,
            provenance=Provenance(origin=consumption.provenance.origin, kind=ValueKind.measured),
            decided_by=Audit(at=at, by_system=SYSTEM),
        )
        _close_confirmation(conn, consumption.id, "expired")
        out.append(_record(conn, attribution, stable_id("correlation", str(consumption.id))))
    return out


def _pending(conn: sqlite3.Connection, cid: UUID) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM billing_confirmation WHERE consumption_event_id = ?"
            " AND status = 'pending'",
            (str(cid),),
        ).fetchone()
        is not None
    )


def _close_confirmation(conn: sqlite3.Connection, cid: UUID, status: str) -> None:
    conn.execute(
        "UPDATE billing_confirmation SET status = ? WHERE consumption_event_id = ?",
        (status, str(cid)),
    )


# --- gravação ---------------------------------------------------------------------------------


def _record(
    conn: sqlite3.Connection, new: Attribution, correlation_id: UUID
) -> de.BillingAttributionChanged:
    """Grava `new` como ativa; a anterior (se houver) fica `superseded`. Idempotente por id."""
    old = active_attribution(conn, new.consumption_event_id)
    if old is not None and old.id != new.id:
        old, new = supersede(old, replace(new, supersedes_id=old.id))
        conn.execute(
            "UPDATE billing_attribution SET status = 'superseded', json = ? WHERE id = ?",
            (old.model_dump_json(), str(old.id)),
        )
    if old is None or old.id != new.id:
        conn.execute(
            "INSERT INTO billing_attribution (id, household_id, consumption_event_id, status,"
            " supersedes_id, json, created_at) VALUES (?,?,?,'active',?,?,?)",
            (
                str(new.id),
                str(new.household_id),
                str(new.consumption_event_id),
                str(new.supersedes_id) if new.supersedes_id else None,
                new.model_dump_json(),
                new.decided_by.at.isoformat(),
            ),
        )
    return de.BillingAttributionChanged(
        id=stable_id("billing.attribution_changed", str(new.id)),
        ts=new.decided_by.at,
        household_id=new.household_id,
        correlation_id=correlation_id,
        provenance=new.provenance,
        data=new,
    )


record = _record  # para correções auditadas fora do atribuidor (contestações, BILL-06)


# --- leituras partilhadas com o fecho da fatura ------------------------------------------------


def active_attribution(conn: sqlite3.Connection, cid: UUID) -> Attribution | None:
    row = conn.execute(
        "SELECT json FROM billing_attribution WHERE consumption_event_id = ? AND status = ?",
        (str(cid), AttributionStatus.active.value),
    ).fetchone()
    return Attribution.model_validate_json(row["json"]) if row else None


def load_consumption(conn: sqlite3.Connection, cid: UUID) -> ConsumptionEvent:
    row = conn.execute("SELECT json FROM billing_consumption WHERE id = ?", (str(cid),)).fetchone()
    return ConsumptionEvent.model_validate_json(row["json"])


def active_tenants(
    conn: sqlite3.Connection, household_id: UUID, at: datetime
) -> list[tuple[UUID, UUID | None]]:
    """Inquilinos com contrato ativo no dia (fuso da casa) de `at`: (morador, quarto)."""
    tz = conn.execute(
        "SELECT timezone FROM household WHERE id = ?", (str(household_id),)
    ).fetchone()["timezone"]
    day = at.astimezone(ZoneInfo(tz)).date().isoformat()
    rows = conn.execute(
        "SELECT resident_id, room_id FROM membership WHERE household_id = ? AND role = 'tenant'"
        " AND status IN ('active', 'ended') AND starts_on <= ?"
        " AND (ends_on IS NULL OR ends_on >= ?) ORDER BY resident_id",
        (str(household_id), day, day),
    ).fetchall()
    return [(UUID(r["resident_id"]), UUID(r["room_id"]) if r["room_id"] else None) for r in rows]
