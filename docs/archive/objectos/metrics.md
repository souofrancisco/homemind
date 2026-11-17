# Métricas

> **ARQUIVADO — ObjectOS.** Só consulta histórica; não descreve a Conta Certa. Índice: [README](README.md).

Só entram na coluna «Medido» valores com evidência. **REAL** = hardware/serviço real; **SIMULADO** = FakeHome, clip sintético ou IdP de teste.

## Critérios da demo

| Critério | Alvo | Medido | Tipo | Como medir |
|---|---|---|---|---|
| Leitura RTSP contínua | 10 min, 0 quedas | 600 s, 5974 frames, 10,0 FPS, 0 quedas, maior intervalo 609 ms, 1920×1080 (17/11, via relay RTSP) | REAL | `python -m homemind.features.video.medir --minutos 10` |
| Atraso câmara → ecrã | < 1,5 s | por medir | — | guia VID-02 |
| FPS de inferência (objetos + pose) | ≥ 10 com GPU | ~40 FPS em Apple Silicon (MPS), ~9 FPS em CPU, imagem sintética 640×480 (PR #45) | REAL (não é a GPU nem a câmara da demo) | guia YOLO-02 |
| Gestos corretos | 10/10, 0 falsos positivos | por medir no clip MEARI | — | guia GES-01/02, afinador |
| Latência gesto → luz | < 4 s | por medir | — | `medir_latencia` (software) e guia LAT-01/02 |
| Demos completas seguidas | 10 | por medir | — | guia DEMO-01 |

## MCP Altice (REAL, só leituras)

| Medida | Valor | Data |
|---|---|---|
| Abrir sessão (OAuth + initialize) | ~0,8 s (até ~2 s na 1.ª chamada) | 17/11 |
| `get_device_details` em sessão quente | 0,65–0,87 s | 17/11 |
| Polling de lâmpada + tomada | ~0,9 s por ciclo de 5 s | 17/11 |
| Escrita com efeito físico confirmado | **nenhuma** (bloqueado, ver `mcp-capabilities.md`) | — |
| Consumo em W | **indisponível** (unidade de `instantPower` não declarada) | — |

## Software (verificado em 17/11, ver `estado-para-amanha.md`)

| Medida | Valor | Tipo |
|---|---|---|
| `pytest` | 199 testes, ~10 s | fakes |
| Evento simulado → `home_state` ativo no WebSocket | ~2 ms (uma medição) | SIMULADO (FakeHome, processo real) |
| Encerramento do servidor (SIGINT) | < 1 s, sem tarefas pendentes | REAL (processo) |

## Poupança de energia

A poupança apresentada é uma **estimativa** (W da tomada ao suspender × tempo suspenso × tarifa). Com FakeHome usa 60 W fixos (SIMULADO). Com MCP fica a zero até a unidade de `instantPower` ser confirmada. Nunca apresentar como leitura de contador.
