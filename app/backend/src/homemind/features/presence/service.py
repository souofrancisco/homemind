"""Pistas de presença por pessoa (PRES-03) e fusão no estado do morador (PRES-04).

Regras (contrato `PresenceEvent`, decisão D-30/D-31):
- o Wi-Fi só produz `in`, e só quando um telemóvel registado COM opt-in aparece; a sua ausência
  nunca gera nada (nem `out`);
- não há check-in manual: a presença vem da câmara (porta) e do Wi-Fi; só a RESPOSTA a «estás em
  casa?» (pergunta do sistema, em caso de contradição) vira pista manual;
- uma pista individual só se grava com `Membership.presence_opt_in` (e membership ativa); a
  verificação e a gravação do evento acontecem na MESMA transação: a revogação é imediata.

Fusão (`fusion.py`, pura): dois consumidores do barramento recalculam o estado do morador quando
chega uma pista (`presence.cue_recorded`) ou uma passagem na porta (`presence.door_crossed`); um
*ticker* reavalia periodicamente (a tolerância passa sem eventos). Mudanças saem em
`presence.changed`; contradições em `presence.confirmation_needed` (pergunta, nunca acusação).
"""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind, new_id, stable_id
from homemind.contracts.domain_events import (
    DomainEvent,
    EnergyConsumptionDetected,
    NotificationResponded,
    PresenceChanged,
    PresenceConfirmationNeeded,
    PresenceCueRecorded,
    PresenceOccupancyChanged,
    PresenceSourceRevokedEvent,
    StoredEvent,
)
from homemind.contracts.notification import RefType
from homemind.contracts.presence import (
    ConsentReason,
    ConsentSource,
    HouseOccupancy,
    OccupancyState,
    PersonPresence,
    PresenceConfirmationRequest,
    PresenceDevice,
    PresenceEvent,
    PresenceSource,
    PresenceSourceRevoked,
    PresenceState,
    UncertainReason,
)
from homemind.core.db import Database
from homemind.core.events import EventBus, EventStoreError, append_event
from homemind.features.presence import consent, repo
from homemind.features.presence.consent_texts import TEXT_VERSION
from homemind.features.presence.fusion import CUE_WINDOW, FusionParams, Signals, fuse
from homemind.features.presence.occupancy import WINDOW, Residents, compute_occupancy
from homemind.features.presence.wifi import WifiScanner, match_key, normalize_mac

log = logging.getLogger(__name__)

WIFI_CONFIDENCE = 0.8  # «conta muito a favor»
APPLIANCE_CONFIDENCE = 0.6
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
        or not consent.collection_allowed(
            conn, ev.household_id, resp.resident_id, ConsentSource.manual, resp.responded_at
        )
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
        fusion: FusionParams | None = None,
        appliance_fresh_s: float = 300.0,
        wifi_enabled: bool = False,
        wifi_interval_s: float = 30.0,
        camera_state: Callable[[], tuple[bool, Origin]] | None = None,
    ) -> None:
        # (câmara ativa, origem). Sem fonte configurada: não está ativa (conservador).
        self.camera_state = camera_state or (lambda: (False, Origin.simulated))
        self.db, self.bus, self.salt, self.clock = db, bus, salt, clock
        self.refresh_s = refresh_s
        self.fusion = fusion or FusionParams()
        self.appliance_fresh = timedelta(seconds=appliance_fresh_s)
        self.wifi_enabled, self.wifi_interval_s = wifi_enabled, wifi_interval_s
        self._wifi_last_ok: datetime | None = None
        self._last_cue: dict[tuple[UUID, UUID], datetime] = {}
        self._prev_seen: set[tuple[UUID, UUID]] = set()

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

    # --- consentimento por fonte (PRIV-03 #51) -----------------------------------------------

    async def consents(self, household_id: UUID, resident_id: UUID) -> list[sqlite3.Row]:
        """Linhas de `presence_source_consent` do próprio (sem linha = desligada)."""
        return await self.db.run(lambda c: consent.list_states(c, household_id, resident_id))

    async def grant_source(
        self, household_id: UUID, resident_id: UUID, source: ConsentSource, text_version: str
    ) -> None:
        """Liga uma fonte. Exige o opt-in global e a versão atual do texto. Idempotente."""
        if text_version != TEXT_VERSION:
            raise DeviceError("text_version_outdated")
        now = self.clock()

        def tx(conn: sqlite3.Connection) -> None:
            if not repo.has_presence_opt_in(conn, household_id, resident_id, now):
                raise DeviceError("presence_opt_in_required")
            consent.grant(conn, household_id, resident_id, source, now)

        await self.db.run(tx)

    async def revoke_source(
        self, household_id: UUID, resident_id: UUID, source: ConsentSource
    ) -> tuple[int, int]:
        """Desliga UMA fonte e apaga só os dados dela, numa transação; recalcula o estado com o
        que sobra (sem pistas, o estado deixa de existir: nunca fica um «fora» ou «em casa» que
        vinha da fonte revogada). Publica `presence.source_revoked` (a faturação descarta a sua
        cópia) e o novo estado. Idempotente: repetir não muda nada nem regista outra revogação."""
        now = self.clock()

        def tx(conn: sqlite3.Connection) -> tuple[tuple[int, int], list[DomainEvent]]:
            changed = consent.revoke_flag(
                conn, household_id, resident_id, source, now, ConsentReason.resident
            )
            counts = consent.erase_source_data(conn, household_id, resident_id, source, now)
            if not (changed or counts[0] or counts[1]):
                return counts, []
            prov = Provenance(origin=Origin.real, kind=ValueKind.measured)
            events: list[DomainEvent] = [
                PresenceSourceRevokedEvent(
                    ts=now,
                    household_id=household_id,
                    provenance=prov,
                    data=PresenceSourceRevoked(resident_id=resident_id, source=source),
                )
            ]
            new, _ = self.compute(conn, household_id, resident_id, now)
            if new is None:
                conn.execute(
                    "DELETE FROM presence_state WHERE household_id = ? AND resident_id = ?",
                    (str(household_id), str(resident_id)),
                )
            elif repo.has_presence_opt_in(conn, household_id, resident_id, now):
                repo.upsert_state(conn, household_id, new, now)
                events.append(
                    PresenceChanged(
                        ts=now, household_id=household_id, provenance=new.provenance, data=new
                    )
                )
            return counts, [append_event(conn, e).event for e in events]

        counts, events = await self.db.run(tx)
        for ev in events:
            await self.bus.publish(ev)
        return counts

    # --- fusão (PRES-04) --------------------------------------------------------------------

    def wifi_ok(self, now: datetime) -> bool:
        """O varrimento está vivo: houve um varrimento bem-sucedido há pouco. Desligado ou
        parado = não está vivo (o silêncio do Wi-Fi deixa de ser informação)."""
        if not self.wifi_enabled or self._wifi_last_ok is None:
            return False
        return now - self._wifi_last_ok <= timedelta(seconds=max(3 * self.wifi_interval_s, 120))

    def _signals(self, conn: sqlite3.Connection, hid: UUID, rid: UUID, now: datetime) -> Signals:
        return Signals(
            wifi_expected=repo.count_active_devices(conn, hid, rid) > 0
            and consent.has_source_consent(conn, hid, rid, ConsentSource.wifi),
            wifi_ok=self.wifi_ok(now),
            sole_candidate=repo.others_in(conn, hid, rid) == 0,
        )

    def compute(
        self, conn: sqlite3.Connection, hid: UUID, rid: UUID, now: datetime
    ) -> tuple[PersonPresence | None, bool]:
        """Estado fundido em `now` (sem gravar). `None`: nunca houve pistas deste morador."""
        since = now - CUE_WINDOW
        verdict = fuse(
            rid,
            repo.load_cues(conn, hid, rid, since),
            repo.load_doors(conn, hid, since),
            now,
            self.fusion,
            repo.get_state(conn, hid, rid),
            self._signals(conn, hid, rid, now),
        )
        return verdict.presence, verdict.ask

    def current_state(
        self, conn: sqlite3.Connection, hid: UUID, rid: UUID, now: datetime
    ) -> PersonPresence:
        """Para a API: o estado, ou «incerto: sem pistas» se ainda não houve nenhuma."""
        presence, _ = self.compute(conn, hid, rid, now)
        if presence is not None:
            return presence
        since = min(repo.membership_start(conn, hid, rid), now)
        return PersonPresence(
            resident_id=rid,
            state=PresenceState.uncertain,
            since=since,
            confidence=0.0,
            provenance=Provenance(origin=Origin.real, kind=ValueKind.inferred),
            sources=[],
            reason=UncertainReason.no_recent_cues,
        )

    def apply_fusion(
        self, conn: sqlite3.Connection, hid: UUID, rid: UUID, now: datetime
    ) -> list[DomainEvent]:
        """Recalcula, grava o estado e devolve os eventos a publicar (não os grava)."""
        if not repo.has_presence_opt_in(conn, hid, rid, now):
            return []  # sem `presence_opt_in` não se grava estado nenhum
        prev = repo.get_state(conn, hid, rid)
        new, ask = self.compute(conn, hid, rid, now)
        if new is None:  # sem pistas na janela: mantém o que havia, nunca inventa «fora»
            return []
        repo.upsert_state(conn, hid, new, now)
        events: list[DomainEvent] = []
        if prev is None or (prev.state, prev.reason) != (new.state, new.reason):
            events.append(
                PresenceChanged(ts=now, household_id=hid, provenance=new.provenance, data=new)
            )
        last = repo.last_confirmation_at(conn, hid, rid)
        if (
            ask
            and consent.has_source_consent(conn, hid, rid, ConsentSource.manual)
            and new.reason is not None
            and (last is None or now - last >= self.fusion.confirmation_cooldown)
        ):
            req = PresenceConfirmationRequest(
                id=new_id(),
                resident_id=rid,
                reason=new.reason,
                expires_at=now + self.fusion.confirmation_ttl,
            )
            repo.insert_confirmation(conn, hid, req, now)
            events.append(
                PresenceConfirmationNeeded(
                    ts=now, household_id=hid, provenance=new.provenance, data=req
                )
            )
        return events

    def on_presence_input(self, conn: sqlite3.Connection, stored: StoredEvent) -> list[DomainEvent]:
        """Consumidor: uma pista (é de uma pessoa) ou uma passagem na porta (anónima: reavalia
        todos os moradores da casa)."""
        ev = stored.event
        now = max(self.clock(), ev.ts)
        if isinstance(ev, PresenceCueRecorded):
            residents = [ev.data.resident_id]
        else:
            residents = repo.active_tenants(conn, ev.household_id, now)
        out: list[DomainEvent] = []
        for rid in residents:
            out += self.apply_fusion(conn, ev.household_id, rid, now)
        return out + self.apply_house(conn, ev.household_id, now)

    def on_consumption_detected(
        self, conn: sqlite3.Connection, stored: StoredEvent
    ) -> list[DomainEvent]:
        """Um aparelho pessoal que ACABOU de ligar é uma pista `in` do dono. Um que já estava
        ligado (consumo começado há mais do que `appliance_fresh`) não prova nada: ignora-se."""
        ev = stored.event
        if not isinstance(ev, EnergyConsumptionDetected):
            return []
        d = ev.data
        owner = d.appliance_owner_resident_id
        if owner is None or ev.ts - d.started_at > self.appliance_fresh:
            return []
        cue_id = stable_id("appliance-cue", str(d.id))
        if repo.cue_exists(conn, cue_id) or not consent.collection_allowed(
            conn, ev.household_id, owner, ConsentSource.appliance, ev.ts
        ):
            return []
        prov = Provenance(origin=d.provenance.origin, kind=ValueKind.inferred)
        return [
            PresenceCueRecorded(
                id=cue_id,
                ts=d.started_at,
                household_id=ev.household_id,
                correlation_id=d.id,
                provenance=prov,
                data=PresenceEvent(
                    id=stable_id("appliance-cue-data", str(d.id)),
                    household_id=ev.household_id,
                    resident_id=owner,
                    ts=d.started_at,
                    state=PresenceState.home,
                    source=PresenceSource.appliance,
                    confidence=APPLIANCE_CONFIDENCE,
                    provenance=prov,
                    consumption_event_id=d.id,
                ),
            )
        ]

    async def tick(self) -> int:
        """Reavalia quem já tem estado: a tolerância passa sem que chegue nenhum evento."""
        now = self.clock()

        def run(conn: sqlite3.Connection) -> list[DomainEvent]:
            out: list[DomainEvent] = []
            houses: dict[UUID, None] = dict.fromkeys(repo.houses_with_house_state(conn))
            for hid, rid in repo.tracked_residents(conn):
                houses[hid] = None
                for ev in self.apply_fusion(conn, hid, rid, now):
                    out.append(append_event(conn, ev).event)
            for hid in houses:
                for ev in self.apply_house(conn, hid, now):
                    out.append(append_event(conn, ev).event)
            return out

        events = await self.db.run(run)
        for ev in events:
            await self.bus.publish(ev)  # idempotente: só acorda os consumidores
        return len(events)

    async def own_state(self, household_id: UUID, resident_id: UUID) -> PersonPresence:
        """Só o próprio morador vê o seu estado (nem colegas, nem senhorio). Os outros módulos
        (regra C da P4) recebem-no por eventos."""
        now = self.clock()
        return await self.db.run(lambda c: self.current_state(c, household_id, resident_id, now))

    def _occupancy(
        self,
        conn: sqlite3.Connection,
        household_id: UUID,
        now: datetime,
        camera_ok: bool,
        camera_origin: Origin,
    ) -> HouseOccupancy:
        """Cálculo ÚNICO da ocupação (cartão e evento). Só lê."""
        home = unknown = 0
        for rid in repo.active_tenants(conn, household_id, now):
            if not repo.has_presence_opt_in(conn, household_id, rid, now):
                unknown += 1
                continue
            presence, _ = self.compute(conn, household_id, rid, now)
            if presence is not None and presence.state is PresenceState.home:
                home += 1
            elif presence is None or presence.state is PresenceState.uncertain:
                unknown += 1
        last = repo.get_house_state(conn, household_id)
        empty_since = last[1] if last and last[0] == OccupancyState.likely_empty.value else None
        doors = repo.load_doors(conn, household_id, now - WINDOW)
        return compute_occupancy(
            doors,
            Residents(home=home, unknown=unknown),
            now,
            camera_ok=camera_ok,
            camera_origin=camera_origin,
            empty_since=empty_since,
        )

    async def occupancy(
        self, household_id: UUID, *, camera_ok: bool, camera_origin: Origin
    ) -> HouseOccupancy:
        """Ocupação agregada (PRES-05): só números, calculados em cada pedido a partir do registo
        da porta e dos estados dos moradores; nada se grava. Qualquer morador da casa a vê."""
        now = self.clock()
        return await self.db.run(
            lambda c: self._occupancy(c, household_id, now, camera_ok, camera_origin)
        )

    def apply_house(self, conn: sqlite3.Connection, hid: UUID, now: datetime) -> list[DomainEvent]:
        """PRES-06: recalcula a ocupação e devolve `presence.occupancy_changed` só se o estado
        mudou (o primeiro `uncertain` só grava). Só descreve: nunca arma nem executa nada."""
        camera_ok, origin = self.camera_state()
        occ = self._occupancy(conn, hid, now, camera_ok, origin)
        prev = repo.get_house_state(conn, hid)
        state = occ.state.value
        if prev is not None and prev[0] == state:
            return []
        repo.set_house_state(conn, hid, state, now)
        if prev is None and occ.state is OccupancyState.uncertain:
            return []
        return [
            PresenceOccupancyChanged(
                id=stable_id(
                    "presence-occupancy",
                    str(hid),
                    prev[0] if prev else "-",
                    state,
                    now.isoformat(),
                ),
                ts=now,
                household_id=hid,
                provenance=occ.provenance,
                data=occ,
            )
        ]

    # --- observações Wi-Fi ------------------------------------------------------------------

    async def observe(self, keys: set[str], origin: Origin) -> int:
        """`keys`: hashes dos aparelhos vistos agora. Só os de telemóveis registados com opt-in
        geram pista `in`; os outros são descartados sem rasto. Devolve quantas pistas gravou."""
        now = self.clock()
        self._wifi_last_ok = now  # chegar aqui = o varrimento correu (mesmo sem aparelhos)
        prov = Provenance(origin=origin, kind=ValueKind.inferred)

        def tx(conn: sqlite3.Connection) -> tuple[list[PresenceCueRecorded], set]:
            emitted: list[PresenceCueRecorded] = []
            seen: set[tuple[UUID, UUID]] = set()
            for d in repo.active_devices(conn):
                ident = (d.household_id, d.resident_id)
                if d.match_key not in keys or ident in seen:
                    continue
                # TRÊS consentimentos: o do telemóvel (`wifi_opt_in`, já filtrado), o da fonte
                # Wi-Fi e o da pessoa (`Membership.presence_opt_in`). Sem qualquer um,
                # descarta-se sem rasto. A decisão e a gravação são da mesma transação.
                if not consent.collection_allowed(
                    conn, d.household_id, d.resident_id, ConsentSource.wifi, now
                ):
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
