"""Presença. Dono: presence (P2).

Três coisas distintas:
- `DoorCrossed`: passagem ANÓNIMA na porta (a câmara nunca sabe quem).
- `PresenceEvent`: pista sobre uma pessoa (Wi-Fi, declaração manual, aparelho pessoal a ligar).
- `PersonPresence`: estado fundido de um morador (em casa / fora / incerto).
E, agregado e anónimo, `HouseOccupancy` (pessoas dentro, visitas só como número).
Nenhum transporta imagem, frame, rosto ou `track_id`. O senhorio nunca os recebe.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from homemind.contracts.common import (
    Confidence,
    ContractModel,
    Origin,
    Provenance,
    ShortText,
    UtcDatetime,
)


class PresenceState(StrEnum):
    home = "in"  # valores da proposta: in | out | uncertain
    away = "out"
    uncertain = "uncertain"


class PresenceSource(StrEnum):
    camera_door = "camera_door"  # só em DoorCrossed / como base do estado fundido
    wifi = "wifi"
    manual = "manual"
    appliance = "appliance"  # aparelho pessoal do morador acabou de ligar (vem de P1)
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


_CUE_SOURCES = (PresenceSource.wifi, PresenceSource.manual, PresenceSource.appliance)


class PresenceEvent(ContractModel):
    """Pista sobre uma pessoa. A câmara não identifica pessoas: só `wifi`, `manual` e
    `appliance`. Só a declaração manual diz «fora»: um aparelho a ligar prova presença, mas um
    aparelho desligado (ou ligado há horas) não prova nada."""

    id: UUID
    household_id: UUID
    resident_id: UUID
    ts: UtcDatetime
    state: PresenceState
    source: PresenceSource
    confidence: Confidence
    provenance: Provenance
    consumption_event_id: UUID | None = None  # exatamente nas pistas `appliance`

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.source not in _CUE_SOURCES:
            raise ValueError("pistas por pessoa só vêm de wifi, manual ou appliance")
        if self.state is PresenceState.uncertain:
            raise ValueError("uma pista diz `in` ou `out`; `uncertain` é da fusão")
        if self.source is PresenceSource.wifi and self.state is PresenceState.away:
            raise ValueError("ausência de Wi-Fi não prova ausência da pessoa")
        if self.source is PresenceSource.appliance and self.state is PresenceState.away:
            raise ValueError("um aparelho não prova ausência")
        if (self.source is PresenceSource.appliance) != (self.consumption_event_id is not None):
            raise ValueError("consumption_event_id exatamente nas pistas de aparelho")
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


class PresenceMeIn(ContractModel):
    """`PUT /api/presence/me`: «cheguei / saí». Só `in` ou `out`; a dúvida é da fusão."""

    state: Literal[PresenceState.home, PresenceState.away]


# --- confirmação na app («estás em casa?») -------------------------------------------------------


class PresenceConfirmationRequest(ContractModel):
    """Emitido por presence quando as pistas se contradizem. P3 transforma-o numa `Notification`
    pessoal (`kind=presence_check`, `ref={type: presence_check, id}`) com as ações de
    `PRESENCE_CONFIRMATION_ACTIONS`; a resposta volta em `notification.responded`.
    Pergunta, nunca acusação nem imagem."""

    id: UUID
    resident_id: UUID  # o único que pode responder (é sobre si)
    reason: UncertainReason
    expires_at: UtcDatetime


PRESENCE_CONFIRMATION_ACTIONS = (PresenceState.home.value, PresenceState.away.value)


# --- ocupação anónima (PRES-05) e casa possivelmente vazia (PRES-06) -----------------------------


class OccupancyState(StrEnum):
    occupied = "occupied"
    likely_empty = "likely_empty"  # candidato a AWAY: nunca arma nada sozinho (fase 2)
    uncertain = "uncertain"


class HouseOccupancy(ContractModel):
    """Ocupação agregada da casa. Visitas só como número; sem quem nem horários por pessoa."""

    ts: UtcDatetime
    state: OccupancyState
    people_inside: Annotated[int, Field(strict=True, ge=0)] | None = None  # None: contagem perdida
    visitors: Annotated[int, Field(strict=True, ge=0)] | None = None
    residents_home: Annotated[int, Field(strict=True, ge=0)]
    provenance: Provenance

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.people_inside is None and self.state is not OccupancyState.uncertain:
            raise ValueError("sem contagem da porta o estado é uncertain")
        if self.state is OccupancyState.likely_empty and (
            self.people_inside or self.visitors or self.residents_home
        ):
            raise ValueError("casa vazia exige zero pessoas, zero visitas e zero moradores")
        if self.state is OccupancyState.occupied and not (
            self.people_inside or self.residents_home
        ):
            raise ValueError("ocupada exige alguém dentro")
        if (
            self.visitors is not None
            and self.people_inside is not None
            and self.visitors > self.people_inside
        ):
            raise ValueError("mais visitas do que pessoas dentro")
        return self


# --- telemóvel registado para Wi-Fi (PRES-03) ----------------------------------------------------


class PresenceDevice(ContractModel):
    """Telemóvel de um morador para a pista Wi-Fi. Interno: `match_key` é um hash do
    identificador de rede (nunca o MAC em claro) e não sai na API (`PresenceDeviceView`).

    `wifi_opt_in` é o consentimento para USAR o Wi-Fi como pista; `Membership.presence_opt_in`
    é outro: partilhar o estado com os colegas de casa."""

    id: UUID
    household_id: UUID
    resident_id: UUID
    label: ShortText  # pseudónimo escolhido pelo morador
    match_key: str = Field(min_length=16, max_length=128, repr=False)
    wifi_opt_in: bool = False
    consented_at: UtcDatetime | None = None
    revoked_at: UtcDatetime | None = None
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.wifi_opt_in and (self.consented_at is None or self.revoked_at is not None):
            raise ValueError("opt-in exige consented_at e nenhuma revogação")
        if self.revoked_at is not None and self.consented_at is None:
            raise ValueError("só se revoga o que foi consentido")
        if self.revoked_at and self.consented_at and self.revoked_at < self.consented_at:
            raise ValueError("revoked_at anterior a consented_at")
        return self


class PresenceDeviceView(ContractModel):
    id: UUID
    label: str
    wifi_opt_in: bool
    consented_at: UtcDatetime | None
    revoked_at: UtcDatetime | None

    @classmethod
    def of(cls, d: PresenceDevice) -> PresenceDeviceView:
        return cls(**d.model_dump(include=set(cls.model_fields)))


# --- câmara da porta (PRES-01) -------------------------------------------------------------------


class VideoSourceKind(StrEnum):
    kit = "kit"  # câmara do kit (se expuser stream/snapshot)
    rtsp = "rtsp"  # outra câmara IP na porta
    clip = "clip"  # clip pré-gravado: SIMULADO
    phone = "phone"  # telemóvel como câmara de recurso: SIMULADO na demo


class CameraStatus(ContractModel):
    """`GET /api/presence/camera/status` (operador). Só diagnóstico: nunca imagem nem URL."""

    source: VideoSourceKind
    origin: Origin
    camera_ok: bool
    fps: Annotated[float, Field(ge=0, le=120, allow_inf_nan=False)] | None = None
    last_frame_at: UtcDatetime | None = None
    door_mask_configured: bool  # tudo fora da soleira mascarado a preto

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.source in (VideoSourceKind.clip, VideoSourceKind.phone) and (
            self.origin is not Origin.simulated
        ):
            raise ValueError("clip e telemóvel são fonte SIMULADA, nunca o feed real do kit")
        if not self.camera_ok and self.fps:
            raise ValueError("câmara em falha não tem fps")
        return self
