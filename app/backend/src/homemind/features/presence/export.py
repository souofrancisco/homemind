"""Exportação dos dados de presença do PRÓPRIO morador (PRIV-03 #51; direito de acesso/
portabilidade, sem afirmar conformidade RGPD: ver docs/modules/presence.md).

Só o que é do morador autenticado, na casa pedida: o consentimento, os telemóveis (sem hash nem
endereço), o estado atual, as pistas, as mudanças de estado, os pedidos «estás em casa?» e os
agregados diários, o consentimento por fonte e o registo de consentimentos. Fica de fora tudo o
que é de outros (colegas, outras casas) e as passagens anónimas da porta (não são dados deste
morador). O senhorio e o operador nunca chegam aqui (`Resource.presence` é `own` só para
inquilinos).
"""

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from homemind.contracts.common import ContractModel, Origin, UtcDatetime
from homemind.contracts.presence import (
    ConsentSource,
    PersonPresence,
    PresenceConsentLogView,
    PresenceDeviceView,
    PresenceSource,
    PresenceState,
    UncertainReason,
)
from homemind.features.presence import consent, repo


class ExportedCue(ContractModel):
    ts: UtcDatetime
    state: PresenceState
    source: PresenceSource
    confidence: float
    origin: Origin


class ExportedChange(ContractModel):
    ts: UtcDatetime
    state: PresenceState
    reason: UncertainReason | None


class ExportedConfirmation(ContractModel):
    created_at: UtcDatetime
    reason: UncertainReason
    answered_at: UtcDatetime | None


class ExportedDay(ContractModel):
    """Agregado diário (sem horários): segundos em cada estado e pistas por fonte."""

    day: str
    seconds_in: int
    seconds_out: int
    seconds_uncertain: int
    cues_wifi: int
    cues_manual: int
    cues_appliance: int
    confirmation_requests: int


class ExportRetention(ContractModel):
    """Quanto tempo os brutos ficam antes de passarem a agregados. `proposal=true`: prazo por
    validar com a equipa e o DPO (P-08)."""

    raw_days: int | None
    proposal: bool


class ExportedSourceConsent(ContractModel):
    source: ConsentSource
    enabled: bool
    updated_at: UtcDatetime | None


class PresenceExport(ContractModel):
    generated_at: UtcDatetime
    household_id: UUID
    presence_opt_in: bool
    devices: list[PresenceDeviceView]
    current_state: PersonPresence | None
    cues: list[ExportedCue]
    changes: list[ExportedChange]
    confirmations: list[ExportedConfirmation]
    daily: list[ExportedDay]
    source_consents: list[ExportedSourceConsent]
    consent_history: list[PresenceConsentLogView]
    retention: ExportRetention


def _events(conn: sqlite3.Connection, hid: UUID, rid: UUID, kind: str) -> list[dict]:
    rows = conn.execute(
        "SELECT payload_json, origin, ts FROM domain_event WHERE household_id = ? AND type = ?"
        " AND json_extract(payload_json, '$.resident_id') = ? ORDER BY ts, seq",
        (str(hid), kind, str(rid)),
    ).fetchall()
    return [{**json.loads(r["payload_json"]), "_origin": r["origin"], "_ts": r["ts"]} for r in rows]


def export_own(
    conn: sqlite3.Connection, hid: UUID, rid: UUID, now: datetime, raw_days: int
) -> PresenceExport:
    opt_in = repo.has_presence_opt_in(conn, hid, rid, now)
    cues = [
        ExportedCue(
            ts=e["ts"], state=e["state"], source=e["source"],
            confidence=e["confidence"], origin=e["_origin"],
        )
        for e in _events(conn, hid, rid, "presence.cue_recorded")
    ]  # fmt: skip
    changes = [
        ExportedChange(ts=e["_ts"], state=e["state"], reason=e.get("reason"))
        for e in _events(conn, hid, rid, "presence.changed")
    ]
    confirmations = [
        ExportedConfirmation(
            created_at=r["created_at"], reason=r["reason"], answered_at=r["answered_at"]
        )
        for r in conn.execute(
            "SELECT created_at, reason, answered_at FROM presence_confirmation"
            " WHERE household_id = ? AND resident_id = ? ORDER BY created_at, id",
            (str(hid), str(rid)),
        )
    ]
    daily = [
        ExportedDay(**{k: r[k] for k in ExportedDay.model_fields})
        for r in conn.execute(
            "SELECT * FROM presence_daily WHERE household_id = ? AND resident_id = ?"
            " ORDER BY day",
            (str(hid), str(rid)),
        )
    ]
    return PresenceExport(
        generated_at=now,
        household_id=hid,
        presence_opt_in=opt_in,
        devices=[PresenceDeviceView.of(d) for d in repo.list_devices(conn, hid, rid)],
        current_state=repo.get_state(conn, hid, rid),
        cues=cues,
        changes=changes,
        confirmations=confirmations,
        daily=daily,
        source_consents=[
            ExportedSourceConsent(
                source=r["source"], enabled=bool(r["enabled"]), updated_at=r["updated_at"]
            )
            for r in consent.list_states(conn, hid, rid)
        ],
        consent_history=[
            PresenceConsentLogView(**dict(r)) for r in consent.list_log(conn, hid, rid)
        ],
        retention=ExportRetention(raw_days=raw_days or None, proposal=True),
    )
