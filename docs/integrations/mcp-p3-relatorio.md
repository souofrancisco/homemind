# Pessoa 3 — relatório final (Home, FakeHome, McpHome, MCP)

> **Relatório histórico (ObjectOS), preservado como passagem do MCP para P1.** Referências a «P3», «motor» e «gesto» são do produto antigo. Ponto de entrada: [altice-mcp.md](altice-mcp.md).

Issues: #9, #10, #11 (fechadas), #12 (aberta). Branch: `feat/pessoa3-finalizar`. Data: 18/11/2026.

## Resumo

A maior parte da parte da P3 já está na `main`, feita pelo Francisco (PR #50, PR #47 e commit `056003f`). Inclui o contrato `Home`, o FakeHome, o McpHome com whitelist, o OAuth, a autorização temporária de escritas e o polling ligado ao motor.

Este branch **não volta a implementar nada disso**. Comparei a `main` com as issues #9 a #12, com o plano (§6) e com o contrato v3 da P4. Encontrei 10 bugs, todos confirmados com probes contra um servidor MCP falso e o SDK real, e corrigi os da P3. Acrescentei também o que faltava para conseguirmos fechar a #12.

Resultado: **216 testes verdes** (eram 199) e `ruff` limpo. Não há dependências novas nem ficheiros alterados do motor (P4), da visão (P1/P2) ou do frontend (P5).

## O que foi feito e porquê

| # | Problema na `main` | Correção | Porque importa |
|---|---|---|---|
| B1 | O SDK `mcp` 1.12.4 envia **cada pedido HTTP duas vezes**, escritas incluídas (`client/auth.py` ~l.548: o reenvio está fora do `if 401`). | `PersistentOAuthClientProvider.async_auth_flow` só repete o pedido depois de um 401 (`connectors/altice_auth.py`). | No servidor de teste, uma escrita na lâmpada passa de 1,26 s para 0,64 s e o gesto até ao estado ativo de 2,37 s para 1,27 s. Isto conta diretamente para o objetivo de < 4 s do gesto à luz (#28). Também cumpre a regra «uma tentativa por escrita». |
| B4 | Não havia maneira de ligar os watts: a unidade só era lida da capability, e o kit real não a declara. | Nova variável `MCP_INSTANTPOWER_UNIT` (`W`, `dW` ou `mW`). Se o dispositivo declarar unidade, essa tem prioridade. Vazia, o comportamento fica igual ao de antes (`consumo_w = null`). | Sem isto, a #12 não se podia fechar mesmo depois de os mentores responderem. |
| B9 | `make mcp-doctor` não mostrava o `instantPower` bruto, mas o guia (MCP-06) pede-o. | O doctor mostra `value`/`min`/`max` e a unidade de `instantPower`, `instantVoltage` e `instantCurrent`, sem IDs. | Permite descobrir a unidade com uma carga conhecida. |
| B2 | Quando a sessão OAuth expirava a meio, o aviso dizia «indisponível (ConnectionError)». | Na sessão persistente, a sessão é fechada antes de responder aos pedidos pendentes, e um erro de login passa a `OAuthReauthRequired`. | O aviso passa a ser «Sessão OAuth MCP expirada; execute make mcp-login no host». |
| B5 | Uma única falha no polling apagava o estado (`ligada = null`). Se a pessoa saísse nesse instante, a luz não era reposta no regresso. | A leitura repete-se uma vez, numa sessão nova, antes de invalidar a cache. Não se repete quando o problema é o login. | Uma falha pontual do Cloudflare deixa de estragar a demo. A falha persistente fica para a P4 (ver Pedidos). |
| B3 | Depois de uma escrita sem resposta, `mcp_ok` ficava a `false` mas a lâmpada continuava a `true`. | O estado passa a desconhecido (`null`). | A UI deixa de mostrar «ligada» com o kit em baixo. |
| B6 | O `power on` era omitido quando a cache dizia que a luz já estava ligada. | O `power` é sempre enviado (idempotente). | Se alguém apagar a luz na app da Altice, já não há falso negativo. |
| B7 | O FakeHome recusava `definir_lampada(False, None, 999)`, mas o contrato diz que o brilho é ignorado ao desligar. | Valida o brilho só com `ligada=True`. | O FakeHome e o McpHome passam a comportar-se da mesma forma. |
| B8 | `altice.call_tool` era código morto e aceitava qualquer tool, incluindo o alarme. | Apagada. | Assim não há forma de contornar a whitelist (#11). |
| — | O `.gitignore` deixou de ignorar `.mcp.json` e `.vscode/mcp.json`. | Voltaram ao `.gitignore`. | Esses ficheiros têm a `X-API-Key` e podiam ir parar a um commit sem querer. |

**Testes novos:**

- `connectors/tests/test_altice_auth.py`: um pedido por chamada; 401 sem ciclo; renovação do token. São 4 testes e falham sem a correção.
- Em `connectors/tests/test_mcp_home.py`:
  - testes de B2 a B7;
  - um teste de conformidade do contrato `Home`, que corre sobre o FakeHome e sobre o McpHome;
  - um teste de integração `Engine` + `McpHome` com MCP falso: gesto, falha do MCP com `desligar tudo` a dar `mcp_unavailable`, e recuperação.

## O que já estava bem e não foi duplicado

- **Sessão MCP persistente** numa tarefa própria. O `CancelledError` interno do SDK nunca escapa, e o polling sobrevive a respostas 502, 500 e 429 (confirmado com probes).
- **Fecho de sessão sem bloquear** (`terminate_on_close=False`) e arranque limitado a 10 s.
- **Escritas controladas:**
  - whitelist exata: 3 tools; na lâmpada só `power`, `brightness` e `color_rgb`; na tomada só `power`;
  - autorização temporária (`make mcp-writes-on`) verificada antes de abrir a sessão;
  - confirmação por releitura, com o RGB normalizado pelo brilho;
  - uma escrita com resultado incerto nunca é repetida.
- **OAuth no Docker** (`compose.mcp*.yaml`, `app/.mcp-auth/`) e os comandos `make mcp-*`.
- **Rotas da P4:** `/api/state`, `/api/status` e `/api/off` (com `off`/`unknown`, `partial_failure` e `mcp_unavailable`, como a P3 definiu).

**Decisão:** a P3 **não** cria `GET /api/home/status` nem `GET /api/home/estado`. O `/api/state` e o `/api/status` dão a mesma informação, o `docs/contratos.md` já não as lista e o frontend não as usa.

## Estado dos contratos

- `contracts/home.py` na `main` cumpre a v3 «tal e qual»:
  - `EstadoCasa` tem `backend`, `mcp_ok`, `lampada{ligada,cor,rgb,brilho}`, `tomada{ligada,consumo_w,consumo_lido_em}`, `atualizado_em` e `aviso`;
  - há 10 cores em `CORES`;
  - o brilho vai de 1 a 100;
  - `None` quer dizer «manter» (nos pedidos) ou «desconhecido» (nas leituras).
- `ler_consumo()` devolve `None` quando não há leitura. Nunca inventa watts.
- O FakeHome e o McpHome passam o mesmo teste de conformidade.

## Pedidos a colegas

- **P4 (motor):** se `_guardado.lampada.ligada is None` no regresso de suspenso, reaplicar `self.modo.acoes` (`engine.py`, função `_repor`). Sem isto, uma falha persistente do MCP no momento da saída faz com que a luz não seja reposta. A B5 já cobre as falhas pontuais.
- **Todos:** as latências em [mcp-demo.md](mcp-demo.md) §9 foram medidas com os pedidos duplicados e têm de ser medidas outra vez.

## O que falta para o projeto funcionar (só com o kit real)

1. `make mcp-login` e depois `make mcp-doctor`. Anotar o `workMode` e o último contacto da lâmpada (MCP-01 e MCP-02 no guia de validação).
2. `make mcp-writes-on`, depois `make mcp-verify what=lamp`, e ver a lâmpada física mudar (MCP-04). Isto **fecha a prova de escrita real** das #10 e #11. Se não mudar, ver as hipóteses H1 a H5 em `docs/mcp-capabilities.md`.
3. `make mcp-verify what=plug` com uma carga segura (MCP-05).
4. **Unidade de `instantPower` (#12):**
   - Ligar uma carga conhecida (por exemplo, 60 W) e ler o valor bruto no `make mcp-doctor`.
   - Pôr `MCP_INSTANTPOWER_UNIT` no `app/.env` e confirmar que o `consumo_w` bate com a carga.
   - Fechar a #12.
5. Testar falhas a sério (MCP-07):
   - Cortar a rede: deve ficar `mcp_ok=false`, os estados a `null` e recuperar sozinho.
   - Nenhuma escrita pode ser repetida.
   - Com a sessão expirada, o aviso tem de mandar fazer `make mcp-login`.
6. Medir a latência do gesto à luz 10 vezes (#28) e atualizar o §9 do [mcp-demo.md](mcp-demo.md).
7. Perguntar aos mentores:
   - Se `update_device_capabilities` é assíncrono.
   - Se `color_rgb` exige `workMode=colour`.
   - Qual é a unidade de `instantPower`.
   - Se `todayConsumption` está em kWh.

## Como verificar

```bash
cd app/backend
.venv/bin/python -m pytest -q          # 216 passed
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
