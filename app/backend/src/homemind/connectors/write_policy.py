"""Política em memória para escritas iniciadas por regras."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class WriteOutcome(StrEnum):
    confirmed = "confirmed"
    refused = "refused"
    failed = "failed"
    unknown = "unknown"


@dataclass(frozen=True)
class WriteResult:
    outcome: WriteOutcome
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is WriteOutcome.confirmed


@dataclass(frozen=True)
class Decision:
    rule_id: str
    approved_by: str
    approved_at: datetime
    valid_until: datetime
    allow_turn_on: bool = False


@dataclass(frozen=True)
class RuleWriteLimits:
    cooldown_s: float = 60.0
    max_per_hour: int = 6
    uncertain_lockout_s: float = 300.0


class RuleWritePolicy:
    def __init__(self, limits: RuleWriteLimits = RuleWriteLimits()) -> None:  # noqa: B008
        self.limits = limits
        self._attempts: dict[str, list[datetime]] = {}
        self._unknown: dict[str, datetime] = {}

    def check(
        self, role: str, changes: list[dict[str, Any]], decision: Decision | None, now: datetime
    ) -> str | None:
        if decision is None:
            return "regra sem decisão explícita"
        if (
            now.utcoffset() is None
            or decision.approved_at.utcoffset() is None
            or decision.valid_until.utcoffset() is None
            or decision.approved_at > now
            or decision.valid_until <= now
            or not 1 <= len(decision.rule_id.strip()) <= 80
            or not 1 <= len(decision.approved_by.strip()) <= 80
            or len(decision.rule_id) > 80
            or len(decision.approved_by) > 80
        ):
            return "decisão inválida ou expirada"
        if (
            role == "plug"
            and not decision.allow_turn_on
            and any(c.get("type") == "power" and c.get("value") == "on" for c in changes)
        ):
            return "ligar um aparelho por regra exige allow_turn_on"
        attempts = self._attempts[role] = [
            t for t in self._attempts.get(role, []) if now - t <= timedelta(hours=1)
        ]
        unknown = self._unknown.get(role)
        if (
            unknown is not None
            and (now - unknown).total_seconds() < self.limits.uncertain_lockout_s
        ):
            return "estado incerto da última escrita; a aguardar"
        if attempts and (now - attempts[-1]).total_seconds() < self.limits.cooldown_s:
            return "cooldown entre escritas por regra"
        if len(attempts) >= self.limits.max_per_hour:
            return "limite horário de escritas por regra"
        return None

    def record(self, role: str, outcome: WriteOutcome, now: datetime) -> None:
        if outcome is WriteOutcome.refused:
            return
        self._attempts[role] = [
            t for t in self._attempts.get(role, []) if now - t <= timedelta(hours=1)
        ] + [now]
        if outcome is WriteOutcome.unknown:
            self._unknown[role] = now
        else:
            self._unknown.pop(role, None)
