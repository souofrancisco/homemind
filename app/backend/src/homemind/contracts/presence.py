"""Presença. Dono: presence (P2).

Três coisas distintas:
- `DoorCrossed`: passagem ANÓNIMA na porta (a câmara nunca sabe quem).
- `PresenceEvent`: pista sobre uma pessoa (Wi-Fi, declaração manual).
- `PersonPresence`: estado fundido de um morador (em casa / fora / incerto).
Nenhum transporta imagem, frame, rosto ou `track_id`. O senhorio nunca os recebe.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import model_validator

from homemind.contracts.common import Confidence, ContractModel, Provenance, UtcDatetime


class PresenceState(StrEnum):
    home = "in"  # valores da proposta: in | out | uncertain
    away = "out"
    uncertain = "uncertain"


class PresenceSource(StrEnum):
    camera_door = "camera_door"  # só em DoorCrossed / como base do estado fundido
    wifi = "wifi"
    manual = "manual"
    fusion = "fusion"


class DoorDirection(StrEnum):
    entered = "in"
    left = "out"


class UncertainReason(StrEnum):
    conflicting_cues = "conflicting_cues"
    no_recent_cues = "no_recent_cues"


class DoorCrossed(ContractModel):
    ts: UtcDatetime
    direction: DoorDirection
    confidence: Confidence
    provenance: Provenance


class PresenceEvent(ContractModel):
    """Pista sobre uma pessoa. A câmara não identifica pessoas: só `wifi` e `manual`."""

    id: UUID
    household_id: UUID
    resident_id: UUID
    ts: UtcDatetime
    state: PresenceState
    source: PresenceSource
    confidence: Confidence
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.source not in (PresenceSource.wifi, PresenceSource.manual):
            raise ValueError("pistas por pessoa só vêm de wifi ou manual")
        if self.source is PresenceSource.wifi and self.state is PresenceState.away:
            raise ValueError("ausência de Wi-Fi não prova ausência da pessoa")
        return self


class PersonPresence(ContractModel):
    resident_id: UUID
    state: PresenceState
    since: UtcDatetime
    confidence: Confidence
    provenance: Provenance
    sources: list[PresenceSource]
    reason: UncertainReason | None = None  # obrigatório em `uncertain`

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if (self.state is PresenceState.uncertain) != (self.reason is not None):
            raise ValueError("`reason` exatamente quando o estado é uncertain")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("fontes repetidas")
        return self
