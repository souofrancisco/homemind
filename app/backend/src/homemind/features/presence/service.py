"""Pistas de presença por pessoa (PRES-03): Wi-Fi opt-in e declaração manual.

Regras (contrato `PresenceEvent`, decisão D-30/D-31):
- o Wi-Fi só produz `in`, e só quando um telemóvel registado COM opt-in aparece; a sua ausência
  nunca gera nada (nem `out`);
- só a declaração manual diz `out`;
- uma pista só se grava se o morador tem membership de inquilino ativa; a verificação e a gravação
  do evento acontecem na MESMA transação, por isso uma revogação tem efeito imediato.
"""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind, new_id, stable_id
from homemind.contracts.domain_events import (
    DomainEvent,
    NotificationResponded,
    PresenceCueRecorded,
    StoredEvent,
)
from homemind.contracts.notification import RefType
from homemind.contracts.presence import (
    PersonPresence,
    PresenceDevice,
    PresenceEvent,
    PresenceSource,
    PresenceState,
)
from homemind.core.db import Database
from homemind.core.events import EventBus, EventStoreError, append_event
from homemind.features.presence import repo
from homemind.features.presence.wifi import WifiScanner, match_key, normalize_mac

log = logging.getLogger(__name__)

WIFI_CONFIDENCE = 0.8  # «conta muito a favor»
MIN_CUE_GAP_S = 60.0  # um telemóvel que oscila não enche o registo de pistas
CONFIRMATION_ACTIONS = {s.value: s for s in (PresenceState.home, PresenceState.away)}


class DeviceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _cue(
    *,
    household_id: UUID,
    resident_id: UUID,
    ts: datetime,
    state: PresenceState,
    source: PresenceSource,
    confidence: float,
    provenance: Provenance,
    event_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> PresenceCueRecorded:
    data = PresenceEvent(
        id=new_id(),
        household_id=household_id,
        resident_id=resident_id,
        ts=ts,
        state=state,
        source=source,
        confidence=confidence,
        provenance=provenance,
    )
    return PresenceCueRecorded(
        id=event_id or new_id(),
        ts=ts,
        household_id=household_id,
        correlation_id=correlation_id or new_id(),
        provenance=provenance,
        data=data,
    )


def person_presence_of(cue: PresenceEvent) -> PersonPresence:
    """Estado provisório a partir de UMA pista (a fusão com várias pistas é a PRES-04)."""
    return PersonPresence(
        resident_id=cue.resident_id,
        state=cue.state,
        since=cue.ts,
        confidence=cue.confidence,
        provenance=cue.provenance,
        sources=[cue.source],
    )


def append_cue(conn: sqlite3.Connection, ev: PresenceCueRecorded) -> bool:
    """Grava a pista se o morador é inquilino ativo (verificação e gravação na mesma transação)."""
    cue = ev.data
    if not repo.is_active_tenant(conn, cue.household_id, cue.resident_id, cue.ts):
        return False
    append_event(conn, ev)
    return True


def on_notification_responded(conn: sqlite3.Connection, stored: StoredEvent) -> list[DomainEvent]:
    """«Estás em casa?» respondido na app → pista manual. Só pedidos que presence emitiu, do
    próprio morador e uma única vez; qualquer outra coisa é ignorada sem erro."""
    ev = stored.event
    if not isinstance(ev, NotificationResponded):
        return []
    ref, resp = ev.data.ref, ev.data.response
    if ref is None or ref.type is not RefType.presence_check:
        return []
    req = repo.get_confirmation(conn, ref.id)
    state = CONFIRMATION_ACTIONS.get(resp.action_id)
    if (
        req is None
        or state is None
        or req["household_id"] != str(ev.household_id)
        or req["resident_id"] != str(resp.resident_id)
        or not repo.is_active_tenant(conn, ev.household_id, resp.resident_id, resp.responded_at)
    ):
        return []
    if not repo.mark_confirmation_answered(conn, ref.id, resp.responded_at):
        return []
    prov = Provenance(origin=ev.provenance.origin, kind=ValueKind.measured)
    return [
        _cue(
            household_id=ev.household_id,
            resident_id=resp.resident_id,
            ts=resp.responded_at,
            state=state,
            source=PresenceSource.manual,
            confidence=1.0,
            provenance=prov,
            event_id=stable_id("presence-answer", str(ev.id)),
            correlation_id=ev.correlation_id,
        )
    ]


class PresenceService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        *,
        salt: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        refresh_s: float = 300.0,
    ) -> None:
        self.db, self.bus, self.salt, self.clock = db, bus, salt, clock
        self.refresh_s = refresh_s
        self._last_cue: dict[tuple[UUID, UUID], datetime] = {}
        self._prev_seen: set[tuple[UUID, UUID]] = set()

    # --- declaração manual ------------------------------------------------------------------

    async def record_manual(
        self, household_id: UUID, resident_id: UUID, state: PresenceState
    ) -> PersonPresence:
        """P-19: a declaração manual é `real/measured` (o contrato não a distingue; o morador
        diz-nos o seu estado). Numa casa `real` nunca é simulada."""
        ev = _cue(
            household_id=household_id,
            resident_id=resident_id,
            ts=self.clock(),
            state=state,
            source=PresenceSource.manual,
            confidence=1.0,
            provenance=Provenance(origin=Origin.real, kind=ValueKind.measured),
        )
        if not await self.db.run(lambda c: append_cue(c, ev)):
            raise DeviceError("not_a_resident")
        await self.bus.publish(ev)  # idempotente: só acorda os consumidores
        return person_presence_of(ev.data)

    # --- telemóveis -------------------------------------------------------------------------

    async def register_device(
        self, household_id: UUID, resident_id: UUID, label: str, address: str
    ) -> PresenceDevice:
        """Opt-in explícito (o chamador exige `consent=true`). O MAC só existe nesta função:
        calcula-se o hash e descarta-se."""
        if not self.salt:
            raise DeviceError("wifi_unconfigured")
        try:
            key = match_key(self.salt, address)
        except ValueError as e:
            raise DeviceError("invalid_address") from e
        now = self.clock()
        device = PresenceDevice(
            id=new_id(),
            household_id=household_id,
            resident_id=resident_id,
            label=label,
            match_key=key,
            wifi_opt_in=True,
            consented_at=now,
            created_at=now,
        )

        def tx(conn: sqlite3.Connection) -> None:
            if repo.count_active_devices(conn, household_id, resident_id) >= (
                repo.MAX_DEVICES_PER_RESIDENT
            ):
                raise DeviceError("device_limit")
            if repo.key_in_use(conn, household_id, key):
                raise DeviceError("device_already_registered")
            repo.insert_device(conn, device)

        await self.db.run(tx)
        return device

    async def list_devices(self, household_id: UUID, resident_id: UUID) -> list[PresenceDevice]:
        return await self.db.run(lambda c: repo.list_devices(c, household_id, resident_id))

    async def revoke_device(self, household_id: UUID, resident_id: UUID, device_id: UUID) -> bool:
        now = self.clock()
        return await self.db.run(
            lambda c: repo.revoke_device(c, household_id, resident_id, device_id, now)
        )

    # --- observações Wi-Fi ------------------------------------------------------------------

    async def observe(self, keys: set[str], origin: Origin) -> int:
        """`keys`: hashes dos aparelhos vistos agora. Só os de telemóveis registados com opt-in
        geram pista `in`; os outros são descartados sem rasto. Devolve quantas pistas gravou."""
        now = self.clock()
        prov = Provenance(origin=origin, kind=ValueKind.inferred)

        def tx(conn: sqlite3.Connection) -> tuple[list[PresenceCueRecorded], set]:
            emitted: list[PresenceCueRecorded] = []
            seen: set[tuple[UUID, UUID]] = set()
            for d in repo.active_devices(conn):
                ident = (d.household_id, d.resident_id)
                if d.match_key not in keys or ident in seen:
                    continue
                # DOIS consentimentos: o do telemóvel (`wifi_opt_in`, já filtrado) e o da pessoa
                # (`Membership.presence_opt_in`). Sem qualquer um, descarta-se sem rasto.
                if not repo.has_presence_opt_in(conn, d.household_id, d.resident_id, now):
                    continue
                seen.add(ident)
                last = self._last_cue.get(ident)
                gap = MIN_CUE_GAP_S if ident not in self._prev_seen else self.refresh_s
                if last is not None and (now - last).total_seconds() < gap:
                    continue
                ev = _cue(
                    household_id=d.household_id,
                    resident_id=d.resident_id,
                    ts=now,
                    state=PresenceState.home,
                    source=PresenceSource.wifi,
                    confidence=WIFI_CONFIDENCE,
                    provenance=prov,
                )
                try:
                    append_event(conn, ev)
                except EventStoreError as e:  # ex.: pista simulada numa casa `real`
                    log.warning("pista Wi-Fi recusada (%s)", type(e).__name__)
                    continue
                emitted.append(ev)
            return emitted, seen

        emitted, seen = await self.db.run(tx)
        self._prev_seen = seen
        for ev in emitted:
            self._last_cue[(ev.household_id, ev.data.resident_id)] = now
            await self.bus.publish(ev)
        return len(emitted)

    async def observe_addresses(self, addresses: set[str], origin: Origin) -> int:
        """Do varrimento em memória para hashes: o MAC não passa daqui."""
        keys = {match_key(self.salt, a) for a in addresses}
        return await self.observe(keys, origin)


class WifiPoller:
    """Varre a rede a cada `interval_s` (numa thread). Um varrimento falhado não gera pistas."""

    def __init__(self, service: PresenceService, scanner: WifiScanner, interval_s: float) -> None:
        self.service, self.scanner, self.interval_s = service, scanner, interval_s

    async def run_once(self) -> int:
        try:
            addresses = await asyncio.to_thread(self.scanner.scan)
        except Exception as e:  # noqa: BLE001 - falha de rede/SO: sem pistas, nunca `out`
            log.warning("varrimento Wi-Fi falhou (%s)", type(e).__name__)
            return 0
        return await self.service.observe_addresses(
            {normalize_mac(a) for a in addresses}, Origin(self.scanner.origin)
        )

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as e:  # noqa: BLE001 - o ciclo não pode morrer
                log.error("ciclo Wi-Fi falhou (%s)", type(e).__name__)
            await asyncio.sleep(self.interval_s)
