# Roadmap P0 / P1 / P2

**PLANEADO.** A equipa tem poucos dias; o PDF estimava 2 dias de código + 1 de ensaio (§19). **Datas não confirmadas:** os documentos antigos referiam resumo PDF a 18/11/2026 19h00 e apresentação a 20/11 17h30 ([archive/objectos/estado-para-amanha.md](../archive/objectos/estado-para-amanha.md), pressuposto 6); confirmar com a organização (P-11).

## Fase 0 — Contratos acordados (antes de qualquer implementação)

### Definição de pronto dos contratos

Cada pessoa só começa a implementar quando, para o seu módulo:

1. O modelo Pydantic proposto em [architecture/contracts.md](../architecture/contracts.md) foi lido e aceite pelas outras quatro pessoas (comentário no PR de contratos).
2. Os eventos que produz e consome estão na tabela de eventos, com `data` essencial.
3. P5 publicou `contracts/*.py` com os modelos aceites e `make contracts` verde.
4. Existe um simulador ou evento falso do que o módulo consome.

**Reunião de contratos (1 h, todos):** rever `Provenance`, `EnergyReading`, `ConsumptionEvent`, `Notification`, `Attribution`, `BillAllocation`, envelope de eventos e papéis. Resultado: PR de contratos de P5, aprovado por P1–P4.

## Hora zero (hardware, em paralelo com a Fase 0)

Baseado no PDF §20 e nos bloqueios conhecidos ([risks.md](risks.md)). Cada verificação decide um ramo do plano; **nada é REAL antes de ter PASS no [guia de validação](guia-validacao-manual.md)**.

| # | Verificação | Dono | Se falhar |
|---|---|---|---|
| 1 | OAuth MCP a partir do backend (`make mcp-login`, `make mcp-doctor`) | P1 | Já provado em leituras; repetir no dia |
| 2 | **Unidade de `instantPower`** com carga conhecida; atraso de atualização | P1 | `power_w` estimada por potência nominal × estado (`estimated`); simulador |
| 3 | **Escrita na tomada** (MCP-05) e na lâmpada (MCP-04) | P1 | «Desligo?» e feedback só em modo simulado |
| 4 | Acesso à imagem da câmara (MCP → RTSP → telemóvel) | P2 | Telemóvel como câmara IP ou clip; presença manual |
| 5 | Registo manual de presença na aplicação | P2 + P3 | — |
| 6 | Sensor de clima/contacto: leitura possível dentro da política MCP? | P1 | Fora do MVP |

## P0 — MVP obrigatório

Objetivo: o cenário de [mvp.md](mvp.md), de ponta a ponta, **funcionando sem hardware** (plano B) e com a tomada real quando validada.

| Ordem | Entrega | Dono |
|---|---|---|
| 1 | Contratos acordados e publicados | P5 (todos aprovam) |
| 2 | `core/db`, `core/events`, papéis por role, seed da casa de demo | P5 |
| 3 | Simulador/replay de leituras; `EnergyReading` pelo FakeHome | P1 |
| 4 | Degraus, assinaturas, `ConsumptionEvent` | P1 |
| 5 | Atribuição A/B, fatura, fixtures, recibo | P4 |
| 6 | Centro de notificações + pedido «De quem é esta conta?» com resposta persistida | P3 (+ UI P5) |
| 7 | Orçamento pessoal e alerta de limite | P4 + P3 |
| 8 | Registo manual de presença | P2 |
| 9 | Painel do senhorio (totais por quarto) e recibos nos inquilinos | P5 |
| 10 | Rótulos REAL/SIMULADO, reset da demo, ensaio duas vezes seguidas | P5 |

## P1 — Depois do MVP estável

Preferências de notificação e histórico; assistente que explica recibos; câmara na porta (`DoorCrossed`) e fusão de presença; regra C da conta da sala; previsão linear; plafond por quarto e solidário; picos; contestação; aprendizagem com confirmações; verificações físicas MCP-04/05; páginas de consumo e casa; exportação de dados.

## P2 — Posterior

Aparelho esquecido e «não bate certo»; casa vazia e alerta de entrada; Wi-Fi; ações sugeridas pela IA com confirmação; regras em português → automações; leitura de fatura por LLM multimodal; bi-horário; clustering; push; votação da câmara/regras; remoção do código ObjectOS; segurança/cenários **só se a equipa decidir** ([decisions.md](../decisions.md) P-01).

## O que cortar se o tempo apertar (ordem)

Adaptado do PDF §19.1: (1) automações e regras em português; (2) assistente de IA (a notificação interativa **não** se corta); (3) previsão do fim do mês (fica o aviso por percentagem); (4) opção C; (5) câmara real (fica a presença manual). **Nunca cortar:** deteção de degraus + assinatura + notificação de confirmação + atribuição + fatura com recibos + orçamento com aviso + separação REAL/SIMULADO.

## Fases (relativas ao início do trabalho)

| Fase | Conteúdo |
|---|---|
| Dia 0 (manhã) | Contratos acordados; hora zero em paralelo; P5 entrega `core/db`, `core/events`, papéis |
| Dia 0 (tarde)–Dia 1 | P0 em paralelo (ordem acima) contra simuladores |
| Dia 1 (fim) | Integração: cenário de demo corre com simulador |
| Dia 2 | Hardware onde validado; P1 do roadmap; ensaio cronometrado ×3; vídeo de plano B; congelar |
