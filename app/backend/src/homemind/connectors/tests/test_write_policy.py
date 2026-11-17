from datetime import UTC, datetime, timedelta

from homemind.connectors.write_policy import (
    Decision,
    RuleWriteLimits,
    RuleWritePolicy,
    WriteOutcome,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ON = [{"type": "power", "value": "on"}]
OFF = [{"type": "power", "value": "off"}]
DECISION = Decision("rule", "operator", NOW, NOW + timedelta(hours=3))


def test_decisions_and_precedence():
    p = RuleWritePolicy()
    p.record("plug", WriteOutcome.unknown, NOW)
    assert p.check("plug", ON, None, NOW) == "regra sem decisão explícita"
    invalid = Decision("", "operator", NOW, NOW)
    assert p.check("plug", ON, invalid, NOW) == "decisão inválida ou expirada"
    assert p.check("plug", ON, DECISION, NOW) == "ligar um aparelho por regra exige allow_turn_on"
    assert p.check("plug", OFF, DECISION, NOW) == "estado incerto da última escrita; a aguardar"
    for invalid in (
        Decision("a" * 81, "operator", NOW, NOW + timedelta(hours=1)),
        Decision("r", "", NOW, NOW + timedelta(hours=1)),
        Decision("r", "operator", NOW.replace(tzinfo=None), NOW),
        Decision("r", "operator", NOW + timedelta(seconds=1), NOW + timedelta(hours=1)),
    ):
        assert p.check("lamp", OFF, invalid, NOW) == "decisão inválida ou expirada"
    assert RuleWritePolicy().check("lamp", ON, DECISION, NOW) is None
    assert RuleWritePolicy().check("plug", OFF, DECISION, NOW) is None


def test_attempts_lockout_cooldown_and_sliding_hour():
    p = RuleWritePolicy(RuleWriteLimits(cooldown_s=60, max_per_hour=2, uncertain_lockout_s=120))
    p.record("lamp", WriteOutcome.refused, NOW)
    assert p.check("lamp", ON, DECISION, NOW) is None
    p.record("lamp", WriteOutcome.unknown, NOW)
    assert p.check("lamp", ON, DECISION, NOW + timedelta(seconds=119)).startswith("estado incerto")
    assert p.check("lamp", ON, DECISION, NOW + timedelta(seconds=120)) is None
    p.record("lamp", WriteOutcome.failed, NOW + timedelta(seconds=120))
    assert p.check("lamp", ON, DECISION, NOW + timedelta(seconds=121)).startswith("cooldown")
    assert p.check("lamp", ON, DECISION, NOW + timedelta(seconds=180)).startswith("limite horário")
    assert p.check("lamp", ON, DECISION, NOW + timedelta(hours=1, seconds=1)) is None
    assert p.check("plug", OFF, DECISION, NOW) is None
