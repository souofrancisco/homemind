# Motor ↔ gestos/presença: arranque (P4 → P2)

Confirmado no código do branch `backend-engine` (`features/engine/`).

## 1. Fila e loop são criados no arranque: sim

- O motor arranca no `lifespan` do router `engine`. Nessa altura cria `engine.fila` (`asyncio.Queue`), guarda o event loop e lança a tarefa que consome a fila. Fica disponível em `app.state.engine`.
- A partir da thread de visão, usa só:

  ```python
  engine.publicar_de_thread(evento)  # loop.call_soon_threadsafe(fila.put_nowait, evento)
  ```

  Não bloqueia, e os eventos são processados pela ordem de chegada. `evento` é um `ObjetoLevantado` ou uma `Presenca` de `contracts/eventos.py` (PR #32), com `hora` preenchida.
- ⚠️ **Ordem de arranque:** o FastAPI corre os `lifespan` dos routers por ordem alfabética do nome da pasta da feature. A tua feature tem de arrancar **depois** de `engine`.
  - Se lhe chamares `visao`, `gestos` ou `presenca`, já fica depois, e no teu `lifespan` podes fazer `app.state.engine` diretamente.
  - Se usares um nome que vem antes de `engine` (ex.: `camera`, `deteccao`), o motor ainda não existe quando a tua feature arranca, e o `publicar_de_thread` dá `RuntimeError("motor não iniciado")`.

## 2. Presença inicial: sim, emite `Presenca(True)` no arranque se já houver alguém

- Do teu lado, assume que a presença inicial é `False` e só emites transições. Se no arranque já estiver alguém (2 frames positivos), sai `Presenca(ha_alguem=True)`, e **o motor aceita-a**.
- No motor, a presença começa em `None` (desconhecida; `presence: null` na UI). Qualquer primeiro `Presenca` conta como transição, seja `True` ou `False`. Um `Presenca(False)` inicial também é aceite e, com o motor `inativo`, não faz nada.
- Depois disso, um `Presenca` igual ao anterior é ignorado (sem ruído no registo).
- Um `ObjetoLevantado` também marca presença `True` (o gesto implica alguém), mas a tua presença continua a ser a fonte das transições.
