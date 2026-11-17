# MCP Altice — ponto de entrada

A integração MCP é **central** para a Conta Certa: é por ela que a casa lê dispositivos e (quando autorizado) atua. Esta página resume as regras e a evidência; o detalhe técnico está nos documentos abaixo, **preservados do ObjectOS sem perda**.

| Documento | Conteúdo |
|---|---|
| [mcp-demo.md](mcp-demo.md) | Operação: configuração, login OAuth, modo MCP, escritas autorizadas, estados e erros, tokens, latência |
| [mcp-capabilities.md](mcp-capabilities.md) | Ferramentas e schemas observados, inventário, bloqueio da unidade de `instantPower`, verificação física da lâmpada, hipóteses H1–H5 |
| [mentor-questions.md](mentor-questions.md) | Perguntas abertas aos mentores Altice |
| [mcp-p3-relatorio.md](mcp-p3-relatorio.md) | Relatório de passagem (PR #57): 10 bugs corrigidos, pedido duplicado do SDK `mcp`, `MCP_INSTANTPOWER_UNIT` |
| [../development/guia-validacao-manual.md](../development/guia-validacao-manual.md) | MCP-01…07: como validar hardware e registar o resultado |

Guia oficial de ligação da organização: [references/altice-mcp-guia-ligacao.pdf](../references/altice-mcp-guia-ligacao.pdf) (preservado; P-09 resolvido).

## Regras (inalteradas; nenhuma nesta reorganização foi relaxada)

- Ferramentas usadas: **só** `get_home_devices`, `get_device_details`, `update_device_capabilities`.
- Dispositivos: **só** lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`).
- **Nunca** alarme, segurança, cenários ou timers. As ferramentas `patch_home_security_status`, `post_new_scenario`, `patch_scenario_activation`, `post_execute_scenario`, `post_timer_device` existem no servidor mas **estão fora do âmbito** (decisão P-01 para as rever).
- Escritas físicas: `ENABLE_PHYSICAL_WRITES=false` por omissão **e** grant temporário (`make mcp-writes-on`). Um agente não executa escritas físicas sem autorização explícita do utilizador nessa tarefa.
- Escrita física confirmada **só** por releitura; uma escrita de resultado incerto **nunca** é repetida.
- Segredos (`MCP_API_KEY`, tokens, URL RTSP) só em `app/.env` e `app/.mcp-auth/`. Nunca em logs, erros, testes, issues ou docs. IDs de dispositivos nunca em documentação.
- Não declarar uma ferramenta funcional sem evidência registada.

## Política de escrita por regra (MCP-04) — **IMPLEMENTADO** (sem escritas físicas executadas)

Código: `connectors/write_policy.py` (pura) e `McpHome.tomada_por_regra` / `McpHome.lampada_por_regra`. O caminho manual/ObjectOS (`definir_tomada`, `definir_lampada` → `bool`) **não mudou**.

**Resultado explícito** (`WriteResult`: `outcome` + `reason` sem IDs nem segredos):

| `outcome` | Significa |
|---|---|
| `confirmed` | a releitura mostra o estado pedido |
| `refused` | não saiu nada: sem flag/grant, fora da whitelist, ou a política recusou |
| `failed` | **sabe-se** que não foi aplicado (o MCP recusou; falha antes de enviar; estado final diferente com o dispositivo a contactar a cloud) |
| `unknown` | a escrita foi **enviada** e não se sabe se foi aplicada (transporte caiu depois de enviar, sem releitura, ou o dispositivo não contacta a cloud há ≥ `_SEM_CONTACTO_MIN` min). **Nunca se repete**; só se relê |

Um «aceite» do MCP não é sucesso físico: só a releitura confirma.

**Camadas** (todas têm de passar; a decisão é **adicional** e nunca substitui o grant): flag `ENABLE_PHYSICAL_WRITES` → grant temporal por papel → whitelist por capability → **decisão explícita da regra** → guardas.

**Decisão explícita** (`Decision`): `rule_id`, `approved_by`, `approved_at` e `valid_until` (com fuso horário; não há decisões eternas) e `allow_turn_on`. Sem decisão, ou expirada/inválida, a escrita por regra é `refused` sem tocar no MCP.

**Guardas por regra** (por papel `plug`/`lamp`; valores **decididos pelo utilizador em 17/11/2026**):

| Guarda | Valor |
|---|---|
| Ligar uma tomada | só se a decisão tiver `allow_turn_on` (desligar é sempre permitido; a lâmpada não tem esta guarda) |
| Cooldown entre escritas por regra | 60 s |
| Limite horário | 6 escritas por hora (janela deslizante) |
| Bloqueio depois de `unknown` | 5 min |

`refused` não conta como tentativa; `confirmed`, `failed` e `unknown` contam. Uma falha **antes de enviar** é `failed` (decisão do utilizador), logo conta para o cooldown e o limite, mas não inicia o bloqueio de incerteza. Estado em memória: reinicia com o processo.

**Não feito (PLANEADO):** persistir o resultado e a decisão como evento/auditoria (não há contrato de comando físico em `contracts/`: precisa de acordo da equipa) e ligar as regras (SAFE-01 só levanta alertas hoje). **Validação em hardware não executada:** os testes usam só a sessão falsa `FakeMcp`; nenhuma escrita física foi feita para esta issue.

## O que a Conta Certa pede ao MCP (e o estado)

| Necessidade | Ferramenta | Dentro da política? | Estado (17/11/2026) |
|---|---|---|---|
| Listar e ler dispositivos | `get_home_devices`, `get_device_details` | Sim | **REAL** (leituras) |
| Potência da tomada (`instantPower`) | `get_device_details` | Sim | Valor lido; **unidade não declarada** ⇒ sem `measured` |
| Cortar a tomada | `update_device_capabilities` (`power`) | Sim (com grant) | **Não testado** |
| Cor/brilho da lâmpada (feedback) | `update_device_capabilities` | Sim (com grant) | Resposta «device updated»; **efeito físico não comprovado** |
| Ler sensores de contacto/clima | `get_home_devices`/`get_device_details` | **Fora da seleção atual** do `McpHome` | Proposta de leitura (P-01) |
| Armar alarme, cenários | `patch_home_security_status`, `post_new_scenario`… | **Não** | Fora de âmbito |
| Câmara (imagem) | — (não acedida pelo MCP) | n/a | RTSP/clip; acesso à imagem do kit por provar |

## Evidência real herdada (preservada)

Medições do ObjectOS a 17/11/2026, de `metrics.md` e `estado-para-amanha.md` (arquivados). **São as únicas evidências de hardware que temos.**

| Medida | Valor | Tipo |
|---|---|---|
| Abrir sessão MCP (OAuth + `initialize`) | ~0,8 s (até ~2 s na 1.ª chamada) | REAL |
| `get_device_details` em sessão quente | 0,65–0,87 s | REAL |
| Polling lâmpada + tomada | ~0,9 s por ciclo de 5 s | REAL |
| `tools/list` | 18 ferramentas | REAL |
| Leitura RTSP contínua (relay) | 600 s, 5974 frames, 10,0 FPS, 0 quedas, maior intervalo 609 ms, 1920×1080 | REAL |
| FPS de inferência YOLO (imagem sintética 640×480) | ~40 FPS em Apple Silicon (MPS), ~9 FPS em CPU | REAL, mas não é a GPU nem a câmara da demo |
| Escrita com efeito físico confirmado | **nenhuma** | — |
| Consumo em W | **indisponível** (unidade) | BLOQUEIO EXTERNO |
| NVIDIA | não verificado | — |
| Autenticação Authentik (login real, PKCE) | passa | REAL |

Os valores de gestos, latência «gesto → luz» e as «10 demos seguidas» do ObjectOS **não foram medidos** e deixam de ser relevantes.
