# MVP e demonstração

**PLANEADO.** O MVP demonstra o problema principal — **dividir a conta com justiça e explicação** — com as limitações reais do kit: **uma única tomada com medição**. Contexto: [product/vision.md](../product/vision.md); riscos: [risks.md](risks.md); roadmap: [roadmap.md](roadmap.md).

## Âmbito

Segue o v5.1 §9 e §19 e [decisions.md](../decisions.md) D-14. O MVP é a **Casa Justa + Casa Atenta** com quatro componentes: **M1** visão e contagem na porta, **M2** assinaturas e classificação de aparelhos, **M3** presença, atribuição, orçamentos e anomalias (código, sem modelo treinado), **M4** assistente LLM com ferramentas internas e MCP.

| MVP (F1, com plano B simulado) | Fase 2 (F3) / fora |
|---|---|
| Casa com 4 moradores (seed) | **Segurança AWAY, casa vazia, entrada com casa vazia** (SAFE-02, PRES-06) |
| Registo de aparelhos pessoais e comuns | **Aparelho esquecido após uma saída** (ALERT-04) |
| Leituras de consumo (tomada real ou simulador) | Cenários e regras votadas (SAFE-04, AGENT-04) |
| M2: degraus e identificação **provável** (`confidence`) | Total da casa em tempo real, HAN, MEO Energia (PILOT-02) |
| M1 + M3: contagem na porta (clip/RTSP/simulada), Wi-Fi opt-in ou presença manual, fusão em casa/fora/incerto | Várias tomadas de quarto na bancada (só em produção) |
| Notificação de confirmação na app («É minha / É de todos / Não sei») | Push, leitura de faturas por LLM multimodal |
| Atribuição ao morador ou à conta comum (A/B; C é F2) | Opção C da sala por presença (BILL-07) |
| Orçamento 50/80/100 %, pico em zona comum, lâmpada RGB (se MCP-04 PASS) | Previsão avançada e bi-horário (ALERT-02) |
| M4: assistente na app só com ferramentas read-only (AGENT-01/02) | Ações propostas pela IA (AGENT-03) |
| Regra «janela aberta + aquecedor» **em simulação** (SAFE-01); física só com PASS | |
| Fatura, recibos e painel do senhorio; REAL / SIMULADO / ESTIMADO visível | |

**Limitações assumidas:** uma só tomada mede a extensão da bancada (`main_meter`); a identificação por uma tomada é **probabilística** (cargas simultâneas e a sua localização não se inferem com certeza), pelo que cada resultado leva `confidence` e o resíduo divide-se por igual. Isto deve constar nos contratos, testes e no guião.

## Cenário de demonstração

Casa de 4 moradores: Ana, Bruno, Carla e Diogo (os nomes da tabela de fatura do PDF §7.1; o «João» da demonstração do v5.1 §22 é aqui **a Carla**, para a história e a fatura usarem as mesmas quatro pessoas: decisão D-18). Fatura do mês: 120 €.

| # | Passo | O que se vê na aplicação | Fonte dos dados |
|---|---|---|---|
| 1 | Abrir a casa com 4 moradores | Resumo da casa, quartos, moradores | Seed (`simulated`) |
| 2 | Aparelhos pessoais e comuns já registados (aquecedor do Bruno ~2000 W, secador ~600 W, chaleira da casa ~2000 W…) | Lista de aparelhos por dono/âmbito | Registo manual; potências medidas à mão (`measured` só se a unidade estiver confirmada) |
| 3 | Leituras de consumo a chegar | Gráfico de potência com rótulo de origem | Tomada real **ou** simulador |
| 4 | Liga-se o aquecedor do Bruno | Degrau de +2000 W | Real se unidade confirmada; senão simulador |
| 5 | Identificação provável | «Provável: aquecedor do Bruno (90 %)» — **inferido** | `inferred` (nunca «certo») |
| 6 | A Carla (inquilina) recebe a notificação | «De quem é esta conta?» [É minha] [É de todos] [Não sei] | App |
| 7 | Responde «É minha» | Atribuição à Carla; confirmação «Registado na tua conta» | App + SQLite |
| 8 | Orçamento atualiza | Barra de orçamento da Carla sobe | Cálculo em código |
| 9 | Alerta de limite | «Já gastaste 80 % do teu orçamento» (notificação pessoal) | Cálculo em código |
| 10 | Fecho do mês | Recibo explicado dos 4 (2 simulados, assinalados); painel do senhorio só com totais por quarto | Fixture A de [billing.md](../modules/billing.md) |

### Real, simulado ou estimado — por passo

| Componente | Real **se** | Senão |
|---|---|---|
| Leituras da tomada | MCP-06 aprovado: unidade de `instantPower` confirmada e `MCP_INSTANTPOWER_UNIT` definida | Simulador (`simulated`) ou potência nominal × estado (`estimated`) |
| Corte de uma tomada («desligo?») | MCP-05 aprovado (escrita comprovada com releitura) | Fake; dizer «simulado» |
| Feedback da lâmpada (verde/âmbar/vermelho) | MCP-04 aprovado (lâmpada reage fisicamente) | Mostrar só no ecrã; não prometer |
| Identificação do aparelho | Nunca «real»: é sempre `inferred` com confiança | — |
| Outros 3 quartos | Nunca real no MVP (uma só tomada) | `simulated` |
| Presença | Registo manual real; câmara só se acesso à imagem comprovado | Passagens simuladas |
| Fatura e recibos | Cálculo real em código sobre dados com proveniência; **fatura do mês de demonstração é simulada** | Rótulo SIMULADO nos recibos |

**Regra:** nenhum passo se descreve como REAL no pitch sem PASS no [guia de validação](guia-validacao-manual.md) nesse dia (regra já em uso no ObjectOS). A integração MCP continua a ser parte central (leituras reais já provadas; escritas e consumo por validar — ver [integrations/altice-mcp.md](../integrations/altice-mcp.md)).

## Plano B completo (sem acesso ao hardware)

Objetivo: **toda** a demonstração corre com `HOME_BACKEND=fake` e leituras simuladas, **sem rede, sem câmara, sem MCP**.

| Falha | Ação |
|---|---|
| Sem kit / MCP em baixo / OAuth expirado | `HOME_BACKEND=fake`; o simulador reproduz leituras de aparelhos com perfis conhecidos (aquecedor, secador, chaleira); a UI mostra SIMULADO em tudo. Mostrar à parte as leituras reais do MCP já validadas (`make mcp-doctor`) se estiverem disponíveis |
| Tomada sem unidade confirmada | Simulador ou `estimated`; dizer sempre «estimado» |
| Câmara/Wi-Fi | Presença manual + passagens simuladas |
| Rede | Backend, SQLite e frontend correm em local; assistente/LLM indisponível não bloqueia (o resto funciona) |
| Authentik falha | Sessão iniciada antes de entrar; não fechar o separador |
| Estado corrompido | `reset da demo` (menos de 1 min): recria a casa de demo e o mês simulado |
| Tudo falha | Vídeo gravado do cenário completo (ensaiado) |

O plano B é parte do produto, não uma desculpa: serve para demonstrar a lógica de atribuição e de fatura de forma determinística. **Dito sempre em voz alta.**

## Guião de 3 minutos (proposta)

Adaptado do PDF §22; o grupo de mensagens passa a ser a aplicação; a contagem na porta (M1) entra no passo 2 com a fonte disponível (RTSP, clip ou simulada, sempre rotulada); a segurança AWAY e os aparelhos esquecidos ficam para a fase 2.

| Tempo | O que acontece | O que o júri vê | Aviso |
|---|---|---|---|
| 0:00 | O problema: «120 € ÷ 4 = 30 € para todos — mas o Bruno tem um aquecedor» | Três regras no ecrã | |
| 0:25 | Casa de 4 moradores; aparelhos registados | Resumo da casa | Seed simulado |
| 0:50 | Liga-se o aquecedor do Bruno | Degrau e «Provável: aquecedor do Bruno» | Dizer se leitura real ou simulada |
| 1:15 | A Carla responde no telemóvel «É minha» | Notificação interativa → atribuição | Real na app; dados conforme acima |
| 1:45 | Orçamento sobe; alerta de 80 % | Notificação pessoal | |
| 2:10 | Fecho do mês: recibos | Recibos com «medido / estimado / simulado» + botão de contestar | Fatura simulada |
| 2:35 | Painel do senhorio | Só totais por quarto; sem presença | |
| 2:50 | Frase de fecho | «O teu quarto é teu, as zonas comuns são de todos, e a casa avisa antes de a conta doer.» | |

**Não dizer:** «controlamos a lâmpada/tomada real» sem PASS; precisões ou latências não medidas; valores do PDF (45,12 €, −32 %…) como resultados nossos; «identifica qualquer aparelho».

## Checklist de preparação

- [ ] `make check` e `make smoke` verdes no commit da demo
- [ ] Reset da demo ensaiado (< 1 min); cenário corre 2× seguidas sem intervenção
- [ ] `PROFILE`/seed de demonstração fixos; sessão iniciada; portátil na corrente
- [ ] Modo MCP (se usado): `make mcp-doctor` com último contacto recente; escritas autorizadas pelo tempo da demo; `make mcp-writes-off` no fim
- [ ] Plano B (`HOME_BACKEND=fake`) ensaiado e cronometrado
- [ ] Guião só afirma REAL o que tem PASS nesse dia
