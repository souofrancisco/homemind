import pytest

from homemind.contracts.devices import SignaturePattern
from homemind.features.energy.patterns import infer_pattern


def p(duration_s, cycles=0, first=1000.0, last=1000.0):
    return infer_pattern(
        duration_s=duration_s, cycles=cycles, first_quarter_w=first, last_quarter_w=last
    )


def test_short_wins_over_everything():
    assert p(180, cycles=2, first=2000, last=100) is SignaturePattern.short  # chaleira 3 min


def test_cyclic_heater():
    assert p(3 * 3600, cycles=3) is SignaturePattern.cyclic


def test_decaying_scooter():
    assert p(2 * 3600, first=120, last=40) is SignaturePattern.decaying  # trotinete


def test_continuous_and_boundaries():
    assert p(3600) is SignaturePattern.continuous
    assert p(300) is SignaturePattern.continuous  # 5 min exatos já não é curto
    assert p(3600, first=1000, last=700) is SignaturePattern.continuous  # 30 % exatos não decai
    assert p(3600, first=0, last=0) is SignaturePattern.continuous


@pytest.mark.parametrize("kwargs", [{"duration_s": -1}, {"cycles": -1}, {"first": float("nan")}])
def test_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        p(kwargs.get("duration_s", 600), kwargs.get("cycles", 0), kwargs.get("first", 1.0))
