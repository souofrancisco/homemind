"""Padrão de uma sessão de consumo (partilhado por ENERGY-01 e ENERGY-03). Puro.

Regras decididas pelo utilizador (17/11/2026), por esta ordem:

1. `short`: a sessão dura menos de 5 min;
2. `cyclic`: houve pelo menos um ciclo de termóstato (a carga desceu e voltou ao mesmo nível
   dentro da mesma sessão);
3. `decaying`: a potência média do último quarto da sessão é menor do que 70 % da do primeiro
   quarto (perda > 30 %);
4. `continuous`: nos outros casos.

`first_quarter_w` e `last_quarter_w` são potências médias **acima da base** (em W) do primeiro e do
último quarto do tempo em que a carga esteve ligada. O morador pode corrigir o padrão aprendido.
"""

from __future__ import annotations

import math

from homemind.contracts.devices import SignaturePattern

SHORT_MAX_S = 300.0
DECAY_RATIO = 0.7


def infer_pattern(
    *, duration_s: float, cycles: int, first_quarter_w: float, last_quarter_w: float
) -> SignaturePattern:
    if not all(math.isfinite(v) for v in (duration_s, first_quarter_w, last_quarter_w)):
        raise ValueError("valores não finitos")
    if duration_s < 0 or cycles < 0:
        raise ValueError("duração e ciclos não podem ser negativos")
    if duration_s < SHORT_MAX_S:
        return SignaturePattern.short
    if cycles >= 1:
        return SignaturePattern.cyclic
    if first_quarter_w > 0 and last_quarter_w < DECAY_RATIO * first_quarter_w:
        return SignaturePattern.decaying
    return SignaturePattern.continuous
