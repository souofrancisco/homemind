"""Fusão de pistas num estado por morador: em casa / fora / incerto (PRES-04). Lógica PURA:
sem relógio, base de dados nem barramento (o `now` entra por argumento).

Regras (v5.1 §6.8, CLAUDE.md):
- Wi-Fi e aparelho pessoal a LIGAR contam a favor de «em casa»; a sua ausência não conta contra:
  um telemóvel «a dormir» (sem Wi-Fi) mantém o estado. Um aparelho que continua ligado não prova
  nada (só o evento de ligar chega aqui, e só se for recente: ver `service`).
- «Fora» só por (a) declaração manual `out`, ou (b) saída pela porta E `tolerance` (20–30 min,
  omissão 25) sem nenhuma pista depois dela. A câmara é anónima: uma saída pela porta é de
  «alguém»; qualquer pista do morador durante a tolerância mostra que não foi ele.
- Contradição → `uncertain` (+ pedido de confirmação, nunca acusação): uma pista Wi-Fi ou de
  aparelho depois de o morador estar «fora» e sem nenhuma entrada pela porta (±`door_window`).
- Falha da câmara ou do Wi-Fi = menos pistas, nunca «fora» indevido.
- Nada aqui lê imagens: só `DoorCrossed` (sentido) e pistas de texto.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from homemind.contracts.common import Origin, Provenance, ValueKind
from homemind.contracts.presence import (
    DoorCrossed,
    DoorDirection,
    PersonPresence,
    PresenceEvent,
    PresenceSource,
    PresenceState,
    UncertainReason,
)

CUE_WINDOW = timedelta(hours=48)  # histórico lido; mais antigo não altera o estado


@dataclass(frozen=True)
class FusionParams:
    tolerance: timedelta = timedelta(minutes=25)
    door_window: timedelta = timedelta(seconds=120)  # entrada pela porta ↔ pista que a segue
    door_min_confidence: float = 0.5  # saídas/entradas da câmara abaixo disto não contam
    confirmation_ttl: timedelta = timedelta(minutes=30)
    confirmation_cooldown: timedelta = timedelta(minutes=30)


@dataclass(frozen=True)
class Signals:
    """O que o sistema sabe sobre a saúde das fontes e sobre a casa (não sobre o morador)."""

    wifi_expected: bool = False  # o morador tem um telemóvel com opt-in
    wifi_ok: bool = True  # o varrimento Wi-Fi está vivo agora
    sole_candidate: bool = True  # nenhum outro morador está «em casa»: a saída só pode ser dele

    @property
    def exit_attributable(self) -> bool:
        """Uma saída anónima pela porta só se atribui a este morador se o silêncio do seu Wi-Fi
        é informativo (canal vivo) ou se mais ninguém podia ter saído. Wi-Fi esperado mas em
        falha → nunca «fora» (a fonte falhou, não a pessoa)."""
        if self.wifi_expected:
            return self.wifi_ok
        return self.sole_candidate


@dataclass(frozen=True)
class Verdict:
    presence: PersonPresence | None  # None: nunca houve nenhuma pista deste morador
    ask: bool = False  # contradição: pedir confirmação ao morador


@dataclass
class _Run:
    """Estado da máquina ao percorrer a linha do tempo."""

    # unknown | in | pending (saída pela porta, a contar a tolerância) | out | conflict | silent
    # (saída + tolerância sem poder atribuí-la ao morador: não é «fora», é dúvida)
    state: str = "unknown"
    since: datetime | None = None
    anchor: PresenceEvent | None = None  # última pista positiva
    door_out: DoorCrossed | None = None  # saída que pôs `pending`
    out_start: datetime | None = None  # início do «fora» (declaração ou saída pela porta)
    out_via: str = ""
    used: list[Provenance] = field(default_factory=list)
    sources: list[PresenceSource] = field(default_factory=list)


def _positive(c: PresenceEvent) -> bool:
    return c.state is PresenceState.home


def _add(sources: list[PresenceSource], *new: PresenceSource) -> list[PresenceSource]:
    out = list(sources)
    for s in new:
        if s not in out:
            out.append(s)
    return out


def _entered_between(
    doors: Sequence[DoorCrossed], start: datetime, end: datetime, p: FusionParams
) -> DoorCrossed | None:
    """Houve uma entrada pela porta desde o início do «fora» até `end` (+ janela)?"""
    for d in doors:
        if (
            d.direction is DoorDirection.entered
            and d.confidence >= p.door_min_confidence
            and start <= d.ts <= end + p.door_window
        ):
            return d
    return None


def fuse(
    resident_id: UUID,
    cues: Sequence[PresenceEvent],
    doors: Sequence[DoorCrossed],
    now: datetime,
    params: FusionParams = FusionParams(),  # noqa: B008 - imutável
    previous: PersonPresence | None = None,
    signals: Signals = Signals(),  # noqa: B008 - imutável
) -> Verdict:
    """Estado do morador em `now`. Determinístico; só depende dos argumentos."""
    cues = sorted((c for c in cues if c.resident_id == resident_id and c.ts <= now),
                  key=lambda c: c.ts)  # fmt: skip
    doors = sorted((d for d in doors if d.ts <= now and d.confidence >= params.door_min_confidence),
                   key=lambda d: d.ts)  # fmt: skip
    if not cues:
        return Verdict(None)

    run = _Run()
    timeline: list[tuple[datetime, int, object]] = [(c.ts, 1, c) for c in cues] + [
        (d.ts, 0, d) for d in doors
    ]
    timeline.sort(key=lambda t: (t[0], t[1]))  # à mesma hora, a porta antes da pista

    def settle(upto: datetime) -> None:
        """Uma saída pela porta sem pistas passada a tolerância torna-se «fora»."""
        if run.state == "pending" and run.door_out is not None:
            deadline = run.door_out.ts + params.tolerance
            if upto >= deadline:
                run.state = "out" if signals.exit_attributable else "silent"
                run.since, run.out_start, run.out_via = deadline, run.door_out.ts, "door"
                run.used = [run.door_out.provenance]
                run.sources = [PresenceSource.camera_door]

    for ts, _, item in timeline:
        settle(ts)
        if isinstance(item, DoorCrossed):
            if item.direction is DoorDirection.left and run.state == "in":
                run.state, run.door_out = "pending", item
            elif (
                item.direction is DoorDirection.entered
                and run.state == "conflict"
                and run.anchor is not None
                and run.out_start is not None
                and item.ts >= run.out_start
                and item.ts - run.anchor.ts <= params.door_window
            ):  # a câmara chegou um pouco depois da pista: afinal entrou
                run.state, run.since, run.door_out = "in", run.anchor.ts, None
                run.used = [run.anchor.provenance, item.provenance]
                run.sources = [PresenceSource.camera_door, run.anchor.source]
            continue
        cue: PresenceEvent = item  # type: ignore[assignment]
        if _positive(cue):
            if cue.source is PresenceSource.manual or run.state in (
                "unknown",
                "in",
                "pending",
                "silent",
            ):
                # declaração `in`, ou pista a favor de quem estava (ou podia estar) em casa
                if run.state in ("unknown", "out", "conflict", "silent"):
                    run.since = cue.ts
                run.state, run.anchor, run.door_out = "in", cue, None
                run.used, run.sources = [cue.provenance], [cue.source]
            else:  # `out`/`conflict` + pista Wi-Fi/aparelho: só vale com entrada pela porta
                start = run.out_start or cue.ts
                door = _entered_between(doors, start, cue.ts, params)
                run.anchor = cue
                if door is not None:
                    run.state, run.since, run.door_out = "in", cue.ts, None
                    run.used = [cue.provenance, door.provenance]
                    run.sources = [PresenceSource.camera_door, cue.source]
                else:
                    if run.state != "conflict":
                        run.since = cue.ts
                    run.state = "conflict"
                    run.used = [cue.provenance]
                    run.sources = [cue.source]
        else:  # só a declaração manual diz `out`
            run.state, run.since, run.door_out = "out", cue.ts, None
            run.out_start, run.out_via = cue.ts, "manual"
            run.used, run.sources = [cue.provenance], [PresenceSource.manual]
    settle(now)

    return Verdict(*_present(resident_id, run, now, params, previous, cues[0].ts))


def _combine(items: list[Provenance]) -> Provenance:
    return (
        Provenance.combine(*items)
        if items
        else Provenance(origin=Origin.real, kind=ValueKind.inferred)
    )


def _present(
    resident_id: UUID,
    run: _Run,
    now: datetime,
    params: FusionParams,
    previous: PersonPresence | None,
    first_ts: datetime,
) -> tuple[PersonPresence, bool]:
    prov = _combine(run.used)
    since = run.since or now

    if run.state == "silent":
        out = PersonPresence(
            resident_id=resident_id,
            state=PresenceState.uncertain,
            since=since,
            confidence=0.4,
            provenance=Provenance.combine(prov, _inferred(prov)),
            sources=run.sources,
            reason=UncertainReason.no_recent_cues,
        )
        return _stable(out, previous, first_ts), True

    if run.state == "conflict":
        out = PersonPresence(
            resident_id=resident_id,
            state=PresenceState.uncertain,
            since=since,
            confidence=0.5,
            provenance=prov,
            sources=run.sources,
            reason=UncertainReason.conflicting_cues,
        )
        return _stable(out, previous, first_ts), True

    if run.state == "out":
        manual = run.out_via == "manual"
        out = PersonPresence(
            resident_id=resident_id,
            state=PresenceState.away,
            since=since,
            confidence=1.0 if manual else 0.7,
            provenance=prov if manual else Provenance.combine(prov, _inferred(prov)),
            sources=run.sources,
        )
        return _stable(out, previous, first_ts), False

    # `in` (ou saída pendente da tolerância: continua «em casa», com menos confiança)
    anchor = run.anchor
    assert anchor is not None  # `in`/`pending` só existem depois de uma pista positiva
    pending = run.state == "pending"
    sources = list(run.sources)
    if pending:
        sources = _add(sources, PresenceSource.camera_door)
        conf = 0.5
        prov = Provenance.combine(prov, run.door_out.provenance)  # type: ignore[union-attr]
    else:
        fresh = now - anchor.ts <= params.tolerance
        conf = anchor.confidence if fresh else min(anchor.confidence, 0.6)
    out = PersonPresence(
        resident_id=resident_id,
        state=PresenceState.home,
        since=since,
        confidence=conf,
        provenance=prov,
        sources=sources,
    )
    return _stable(out, previous, first_ts), False


def _inferred(p: Provenance) -> Provenance:
    return Provenance(origin=p.origin, kind=ValueKind.inferred)


def _stable(
    new: PersonPresence, previous: PersonPresence | None, first_ts: datetime
) -> PersonPresence:
    """Se o estado não mudou e o `since` calculado é só o início da janela lida (truncado),
    mantém o `since` anterior: as pistas antigas saem da janela e `since` não pode «andar»."""
    if (
        previous is not None
        and previous.state == new.state
        and previous.reason == new.reason
        and new.since <= first_ts
    ):
        return new.model_copy(update={"since": min(previous.since, new.since)})
    return new
