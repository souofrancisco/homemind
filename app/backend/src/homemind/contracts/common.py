"""Tipos e invariantes comuns dos contratos (Conta Certa).

Decisões (ver docs/architecture/contracts.md):
- Tempo: `datetime` com fuso, sempre normalizado para UTC. Nunca naïve.
- Dinheiro: cêntimos inteiros (`Cents`); nunca `float`.
- Energia: Wh inteiros (`EnergyWh`) em contratos persistidos/financeiros; potência em W
  (`float` finito, é uma medição). `Decimal` só dentro de funções puras (ex.: `cost_cents`).
- Ausência de medição é `None`, nunca `0`.
- IDs internos: UUID. Identificadores externos (MCP, `sub` do Authentik) nunca saem em DTOs.
- Proveniência: duas dimensões, origem (real/simulada) e natureza (medida/estimada/inferida).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum, StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    Field,
    model_validator,
)

from homemind.contracts.base import Contrato


class ContractModel(Contrato):
    """Base dos contratos novos: imutável, sem campos extra e sem NaN/infinito.

    Nas respostas, campos com valor por omissão contam como presentes (o TypeScript gerado não
    os marca opcionais): `null` e campo ausente são coisas diferentes."""

    model_config = Contrato.model_config | {
        "allow_inf_nan": False,
        "json_schema_serialization_defaults_required": True,
    }


def _to_utc(v: AwareDatetime) -> AwareDatetime:
    return v.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
Cents = Annotated[int, Field(strict=True, ge=0, le=10**12)]
SignedCents = Annotated[int, Field(strict=True, ge=-(10**12), le=10**12)]
EnergyWh = Annotated[int, Field(strict=True, ge=0, le=10**9)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
# 100 kW: acima disto numa casa é erro de unidade, não consumo.
PowerW = Annotated[float, Field(ge=0.0, le=100_000.0, allow_inf_nan=False)]
Pct = Annotated[int, Field(strict=True, ge=1, le=200)]
ShortText = Annotated[str, Field(min_length=1, max_length=120)]
LongText = Annotated[str, Field(min_length=1, max_length=500)]
# Período mensal `YYYY-MM`.
Period = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]

_NAMESPACE = uuid.UUID("5f0c3a52-2d6e-4a39-9c0e-c0de0c0ffee0")


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def stable_id(*parts: str) -> uuid.UUID:
    """UUID determinístico (fixtures e testes)."""
    return uuid.uuid5(_NAMESPACE, "/".join(parts))


# --- proveniência --------------------------------------------------------------------------


class Origin(StrEnum):
    real = "real"  # hardware/dados reais
    simulated = "simulated"  # FakeHome, replay, dataset de demonstração


class ValueKind(StrEnum):
    measured = "measured"  # lido de um sensor/declarado, com unidade confirmada
    estimated = "estimated"  # calculado a partir de dados (ex.: lâmpada 9 W × tempo × brilho)
    inferred = "inferred"  # decidido por modelo/regra com incerteza (assinatura, atribuição)


_KIND_RANK = {ValueKind.measured: 0, ValueKind.estimated: 1, ValueKind.inferred: 2}
_LEGACY = {
    "measured": ("real", "measured"),
    "estimated": ("real", "estimated"),
    "inferred": ("real", "inferred"),
    "simulated": ("simulated", "measured"),
}


class Provenance(ContractModel):
    """Origem E natureza do valor: uma inferência sobre dados simulados é `simulated/inferred`."""

    origin: Origin
    kind: ValueKind

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, v: Any) -> Any:
        # Compatibilidade com a proposta antiga (`"inferred"`, `"simulated"`, ...).
        if isinstance(v, str) and v in _LEGACY:
            origin, kind = _LEGACY[v]
            return {"origin": origin, "kind": kind}
        return v

    @property
    def simulated(self) -> bool:
        return self.origin is Origin.simulated

    @classmethod
    def combine(cls, *items: Provenance) -> Provenance:
        """Agregado: simulado se algum for; natureza menos fiável presente."""
        if not items:
            raise ValueError("combine precisa de pelo menos uma proveniência")
        origin = Origin.simulated if any(i.simulated for i in items) else Origin.real
        kind = max((i.kind for i in items), key=_KIND_RANK.__getitem__)
        return cls(origin=origin, kind=kind)


def measured(origin: Origin = Origin.real) -> Provenance:
    return Provenance(origin=origin, kind=ValueKind.measured)


def inferred(origin: Origin = Origin.real) -> Provenance:
    return Provenance(origin=origin, kind=ValueKind.inferred)


def estimated(origin: Origin = Origin.real) -> Provenance:
    return Provenance(origin=origin, kind=ValueKind.estimated)


# --- auditoria e resultados -------------------------------------------------------------------


class Audit(ContractModel):
    """Quem fez e quando. Um autor humano (`by_resident_id`) OU um sistema (`by_system`)."""

    at: UtcDatetime
    by_resident_id: uuid.UUID | None = None
    by_system: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]{0,39}$")] | None = None

    @model_validator(mode="after")
    def _one_actor(self) -> Self:
        if (self.by_resident_id is None) == (self.by_system is None):
            raise ValueError("auditoria: exatamente um de by_resident_id / by_system")
        return self


class OperationStatus(StrEnum):
    succeeded = "succeeded"
    failed = "failed"
    uncertain = "uncertain"  # efeito possivelmente aplicado; nunca repetir às cegas


class OperationResult(ContractModel):
    status: OperationStatus
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")] | None = None
    message: Annotated[str, Field(max_length=300)] | None = None

    @model_validator(mode="after")
    def _failure_has_code(self) -> Self:
        if self.status is not OperationStatus.succeeded and self.code is None:
            raise ValueError("falha ou incerteza exige `code`")
        return self


# --- estados e transições -------------------------------------------------------------------


class InvalidTransitionError(ValueError):
    """Transição de estado não permitida (→ 409 nas rotas)."""


def check_transition[E: Enum](table: Mapping[E, frozenset[E]], old: E, new: E) -> None:
    if new not in table.get(old, frozenset()):
        raise InvalidTransitionError(f"transição inválida: {old.value} -> {new.value}")


def replace[M: BaseModel](model: M, **changes: Any) -> M:
    """Cópia revalidada (os contratos são imutáveis; `model_copy` não revalida)."""
    return type(model).model_validate(model.model_dump() | changes)


# --- dinheiro --------------------------------------------------------------------------------


def cost_cents(energy_wh: int, price_millicents_per_kwh: int) -> int:
    """Custo em cêntimos de `energy_wh` ao preço dado (1 cêntimo = 1000 milicêntimos).

    Aritmética exata em `Decimal`; arredonda uma só vez, ao cêntimo mais próximo (empate ao
    par). Usar sempre esta função: float acumulava erro nas faturas.
    """
    millicents = Decimal(energy_wh) * Decimal(price_millicents_per_kwh) / Decimal(1000)
    return int((millicents / Decimal(1000)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
