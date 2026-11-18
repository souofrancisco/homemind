# Módulos `billing`, `budgets` e `alerts` — atribuição, fatura, orçamentos e alertas

**Dono: P4 (Amorim3000).** **PARCIALMENTE IMPLEMENTADO** (ver «Estado»); o resto é **PLANEADO**. Algoritmo e diagrama: [event-flow.md](../architecture/event-flow.md) §3. Entidades: [data-model.md](../architecture/data-model.md).

**HOUSE-03:** o acesso ao contexto histórico do catálogo está implementado na branch do PR #142,
ainda não integrada na `main`. P4 continua responsável por escolher e justificar a atribuição.

## Responsabilidade

1. **Atribuição:** decidir a quem pertence cada `ConsumptionEvent` (morador ou conta comum) segundo as regras da casa e as respostas dos moradores.
2. **Faturação:** decompor a fatura e calcular a parte de cada morador, com recibos explicáveis.
3. **Orçamentos:** acompanhar o gasto face ao orçamento pessoal e ao plafond por quarto.
4. **Alertas:** picos, aparelhos esquecidos, «não bate certo» — gerar o alerta; a entrega é do módulo `notifications` (P3).

## Recebe / produz

| Recebe | Produz |
|---|---|
| `energy.consumption_detected` / `consumption_closed` (P1) | `Attribution`; `billing.confirmation_needed` quando é preciso perguntar |
| `notification.responded` (P3) | `billing.attribution_changed` |
| `presence.changed` (P2) | Entrada para a regra C e para aparelhos esquecidos |
| Fatura (entrada manual no MVP) | `ElectricityBill`, `BillAllocation`, recibos, `billing.bill_finalized` |
| Orçamentos definidos pelo morador/senhorio | `alerts.threshold_crossed`, `alerts.alert_raised` |

## Contexto temporal do catálogo (HOUSE-03)

P4 depende do port `ApplianceCatalog` de `contracts.appliance_catalog`, injetado no handler; a
feature `billing` não importa `features.appliances`. Para um `ConsumptionEvent` identificado, P4 consulta
`catalog.context_for_consumption(conn, event)`; a consulta usa `event.started_at`, `event.ended_at` e a casa
do evento, nunca o proprietário/membership atual. Para auditar uma transição, usa
`catalog.context_segments_for_consumption(conn, event)`, que devolve intervalos semiabertos com o contexto
válido em cada parte. `None` no resultado singular significa que não há um contexto único seguro:
match desconhecido, catálogo ausente/retirado no instante ou consumo que cruza uma transição.

```python
context = catalog.context_for_consumption(conn, event)
if context is None:
    segments = catalog.context_segments_for_consumption(conn, event)
    # Manter como ambíguo até P4 aplicar a regra aprovada ou pedir confirmação.
```

Estes dados alimentam o motor de atribuição; não são uma `Attribution` nem determinam quem paga.
`owner_resident_id` não identifica quem usou o aparelho. A `home_room_id` é localização habitual;
P4 considera separadamente `event.location`/`event.room_id`, que são evidência observada por P1.
`scope=common` também não escolhe a regra: a regra A/B/C e as respostas pertencem à casa/P4.

Se o evento fechado contém energia total mas atravessa uma mudança, os segmentos só descrevem tempo
e contexto, não kWh por segmento. P4 não deve dividir energia proporcionalmente à duração nem
atribuir tudo ao dono no início/fim. P1 pode emitir episódios com fronteiras coincidentes com as
leituras; sem essa evidência, a energia fica ambígua para confirmação/resíduo segundo a decisão da
casa.

A roster usada no cálculo tem de ser reconstruída pela membership válida na data do consumo e pela
divisão então válida. O fim atual da membership não apaga nem invalida a propriedade histórica; um
morador que saiu continua a aparecer no contexto do evento antigo para contestação, sem ganhar acesso
atual à API da casa.

## Regras da conta comum (PDF §6.2)

| Opção | Comportamento | Prioridade |
|---|---|---|
| **A — por igual** | O consumo comum divide-se por todos os moradores ativos | P0 |
| **B — perguntar** (recomendada pelo PDF) | Cria pedido na aplicação. «É minha»: basta quem assume. Atribuir a outro: pelo menos metade dos moradores aceita (fecha antes se o próprio assumir). Inconclusivo ao fim de 24 h → por igual (D-32) | P0 |
| **C — por presença** | Divide pelos que estavam em casa (usa presença de P2) | P1 |

Só se pergunta quando o custo estimado **do consumo** (utilização completa do aparelho) é ≥ `ask_threshold_cents` (omissão 0,50 €, configurável por casa em `HouseholdPolicy`); abaixo, sem custo estimável ou com a regra A, vai direto para a conta comum. A pergunta pode sair com o consumo ainda a decorrer, logo que passa o limiar (D-32).

## Cálculo da fatura

Ver o fluxograma em [event-flow.md](../architecture/event-flow.md). Resumo:

```text
preço            = (total − fixa) ÷ total_kWh
individual_kWh_i = kWh próprios + parte da conta comum (pela regra)
resíduo_kWh      = total_kWh − Σ individual_kWh        # tem de ser ≥ 0
base             = fixa + resíduo_kWh × preço          # dividida por igual (opção: por dias)
valor_i          = individual_kWh_i × preço + base ÷ N
Σ valor_i        = total                               # arredondar pelo maior resto
```

O recibo mostra **cada linha** com a proveniência dos kWh (`measured` / `estimated` / `inferred` / `simulated`), a percentagem atribuída a alguém e um botão de contestação. Os números do recibo vêm de código; o LLM só os explica ([agent.md](agent.md)).

### Explicação do recibo (BILL-05)

**IMPLEMENTADO (backend):** `GET …/bills/{bill_id}/receipt/explanation` → `ReceiptExplanation`, só para o inquilino (o seu recibo). No fecho (`closing.finalize`) guarda-se em `billing_allocation_item` uma fotografia de cada consumo do período e da decisão ativa (ou da falta dela): a explicação não muda se o consumo ou a decisão mudarem depois; uma correção da fatura é uma nova revisão com a sua própria evidência.

- **Os meus consumos** (`own`): um por consumo, com a linha temporal medição → identificação (aparelho e confiança, ou «não identificado»/ambíguo) → localização → decisão (regra do quarto, «É minha», votação D-32, prazo expirado) → correções → parcela. Os textos são gerados em código a partir dos dados.
- **Conta comum** (`common`): agregada por aparelho, localização e decisão; **sem horas nem pessoas**.
- **Resíduo**: kWh da fatura, kWh atribuídos (casa inteira, agregado), consumos sem decisão no fecho.
- Quem decidiu aparece como `me` / `housemates` / `system`, **nunca** com o id de outro morador. O senhorio e o operador recebem `403` (o senhorio só tem o resumo por quarto).
- **Reconciliação ao cêntimo:** os cêntimos de cada linha `room`/`common` do recibo repartem-se pelos seus consumos (maior resto pelos Wh), logo `fixa + resíduo + Σ own + Σ common = amount_cents`. Se a evidência não bate certo com o recibo (fatura fechada antes desta versão), `evidence_available=false` e as listas vêm vazias: nunca se inventa uma repartição.
- Inclui `equal_split_cents` (o que pagaria com a divisão igual) para responder a «porque é que pago mais?».

**IMPLEMENTADO (app):** no recibo do morador (página de faturas da APP-06), «Porque pago isto?» abre a explicação, que só é pedida ao servidor nesse momento: comparação com a divisão igual, os meus consumos com a linha temporal e a proveniência, a conta comum por aparelho e o não atribuído (`components/billing/ReceiptExplanationView.tsx`; a app não faz contas).

**PLANEADO:** política versionada por data (HOUSE-04: hoje mostra-se a regra da sala em vigor); contagem de votos por consumo. Contestação: ver BILL-06 abaixo (IMPLEMENTADO).

### Exemplos de aceitação (valores do PDF; fatura de 120 € = 24 € fixos + 600 kWh × 0,16 €)

**Fixture A — modelo do PDF §7.1** (individual = quarto + sala + máquina):

| Morador | kWh individuais | Valor |
|---|---|---|
| Ana | 192 | 45,12 € |
| Bruno | 96 | 29,76 € |
| Carla | 64 | 24,64 € |
| Diogo | 38 | 20,48 € |
| **Total** | **390** | **120,00 €** |

Resíduo 210 kWh = 33,60 €; base = (24 € + 33,60 €) ÷ 4 = 14,40 € por pessoa.

**Fixture B — «três regras» do sumário** (só consumo dos quartos: 180, 60, 40, 20 kWh): 46,80 € / 27,60 € / 24,40 € / 21,20 €; base 18,00 €.

O sumário executivo cita 21,20 €; o corpo do documento (§6.2 e §7.1) cita 45,12 / 29,76 / 24,64 / 20,48 €. Os dois conjuntos somam 120,00 € e são **o mesmo algoritmo com dados diferentes**: ambos são testes obrigatórios. Para o MVP vale o A (usa a sala e as máquinas confirmadas na aplicação); o B é a versão mínima. **Os valores são ilustrativos do PDF, não resultados nossos.**

**Fixture C — arredondamento:** 100,00 € repartidos por 3 moradores iguais → 33,34 / 33,33 / 33,33. O cêntimo extra vai a **sorteio reproduzível** (D-34): em `fx.bill_c()` calha à Carla.

**Arredondamento implementado:** cada componente (termo fixo, consumo individual, resíduo) reparte-se em cêntimos inteiros pelo maior resto, com empates resolvidos por sorteio reproduzível (D-34: `draw_order`, semente = casa + mês da fatura). Cada linha do recibo é inteira, as linhas somam o valor de cada morador e `Σ = total` exatamente. Consumos sem atribuição ativa (pergunta pendente, ambíguos, a decorrer) ficam no resíduo: nunca criam dívida.

## Orçamentos (P0 → P1)

- Orçamento pessoal: limiares 50 / 80 / 100 % (omissão do PDF), notificação por limiar **uma só vez** por período (`last_threshold_notified`).
- O gasto comparado inclui **todos os custos** (parte do termo fixo + resíduo + consumo individual), isto é, o valor que o morador vai pagar (D-31).
- Previsão do fim do mês: projeção linear do gasto acumulado (P1). Algoritmos mais complexos ficam fora do MVP.
- «Despesas incluídas» do senhorio (PDF §6.9, §15.3: até X kWh do quarto incluídos na renda, aviso antes de passar): **PLANEADO**, precisa de um campo próprio. **Não** é o `room.included_wh`, que é o plafond solidário de aquecimento (BILL-03, abaixo).

## Alertas (P1/P2)

| Alerta | Gatilho (PDF §6.9) | Prio |
|---|---|---|
| Pico em zona comum | > 1,5 kW durante > 30 min (IMPLEMENTADO); gasto do dia de uma tomada de zona comum ≥ 2× o habitual e ≥ 1 kWh a mais (IMPLEMENTADO) | P0 (ALERT-03 #102) |
| Aparelho esquecido | Aparelho grande ligado com o dono fora há > 1 h (precisa de presença) | P2 |
| Não bate certo | Assinatura do aparelho de um morador fora do quarto dele; consumo noturno anormal | P2 |

Todos produzem `alerts.alert_raised`; o módulo `notifications` decide destinatário (pessoal ou da casa) e entrega.

## Ficheiros existentes reutilizáveis

Nenhum de domínio. Reaproveitar o padrão de feature (`router.py`, `tests/`), `core/errors.py`, o relógio injetado dos testes do motor antigo (`features/engine/tests/`) e `TARIFA_EUR_KWH` de `core/config.py`.

## Estado

| Peça | Estado |
|---|---|
| `features/billing/attribution.py`: primeira decisão (quarto → morador; comum → perguntar/igual) | IMPLEMENTADO (puro, sem persistência) |
| `features/billing/allocation.py`: repartição + arredondamento + recibo por linhas | IMPLEMENTADO (puro, sem persistência) |
| Votação da regra B (D-32) | IMPLEMENTADO no contrato (`confirmation_outcome`) e consumido pelo atribuidor |
| Atribuidor persistente (`features/billing/attributor.py`, consumidor `billing.attributor`, migração `0101`): `energy.consumption_*` → atribuição direta ou `billing.confirmation_needed`; `notification.responded` decidido → atribuição por confirmação; prazo esgotado (tarefa a cada 60 s) → conta comum. Emite `billing.attribution_changed`; nada se apaga (`superseded`) | IMPLEMENTADO |
| Completar o consumo enquanto energy não localiza nem estima custo (BILL-02 #90, `attributor.locate` / `with_cost_estimate`): localização `unknown` → divisão configurada da tomada (`device.room_id`; quarto → `room`, zona comum → `common`; sem divisão, tomada desconhecida ou `main_meter` → fica `unknown`); a localização dada por energy nunca é substituída e a versão localizada é a que billing guarda (recibos e explicação coerentes). Sem `cost_estimate` → energia × preço de referência da casa ou preço médio da última fatura fechada, só para decidir se se pergunta (não se grava); sem preço não se pergunta. Limitação: `device.room_id` não tem histórico, por isso reprocessar consumos antigos usa a configuração atual da tomada | IMPLEMENTADO (provisório até ENERGY-05 #83) |
| Regra da sala por data (política versionada, HOUSE-04 #87) | PLANEADO: hoje nenhum endpoint muda `common_area_rule`; o atribuidor lê a regra atual |
| Entrada da fatura (BILL-01): `BillIn` → pré-visualização → rascunho em `billing_bill` (migração `0100`), `billing.bill_created`, leitura por papel | IMPLEMENTADO (`features/billing/{bills,router}.py`) |
| Fecho do mês (BILL-04, `features/billing/closing.py`, migração `0102`): finalizar (parcelas imutáveis, Σ = total ao cêntimo, `409` ao repetir), correções por revisão (a anterior fica `superseded`), resumo do senhorio por quarto e recibo do inquilino | IMPLEMENTADO |
| Orçamento pessoal e avisos 50/80/100 % (ALERT-01, `features/billing/budgets.py`, migração `0103`): gasto com todos os custos (D-31), desconhecido sem preço, um aviso por limiar e ciclo (ao saltar vários avisa só o mais alto), reset explícito ao redefinir; reavaliado em cada atribuição, fecho de fatura e a cada 60 s. `alerts.threshold_crossed` → aviso pessoal (consumidor `notifications.budget_threshold`) | IMPLEMENTADO |
| Picos nas zonas comuns (ALERT-03, `features/billing/peaks.py`, consumidor `billing.peaks`, migração `0105`): por tomada, a partir de `energy.reading_recorded`; > 1,5 kW durante > 30 min (leituras utilizáveis; lacuna > 10 min recomeça a contagem) → `alerts.alert_raised` (`kind=peak`, potência, início do episódio). Um aviso por incidente (só rearma depois de > 30 min abaixo do limite). Tomada de zona comum → `room_id`; sem divisão ou não registada → «pico de consumo por identificar»; quarto e `main_meter` nunca avisam. Aparelho só com um único consumo a decorrer identificado com confiança ≥ 0,8 e de âmbito `common`. Aviso da casa pelo consumidor `notifications.peak_alert` | IMPLEMENTADO |
| Gasto anormal nas zonas comuns (ALERT-03, `features/billing/anomalies.py`, consumidor `billing.anomalies`, migração `0121`): por tomada **de zona comum** (quartos, contadores gerais e tomadas sem divisão nunca), energia do dia = Σ potência × tempo entre leituras `ok` (intervalos ≤ 10 min; lacunas não se preenchem) e tempo coberto, no fuso da casa. Habitual = mediana dos dias com ≥ 20 h de leituras nos 7 anteriores (mínimo 3; sem isso não avisa). Avisa quando hoje (até agora) ≥ 2× o habitual **e** ≥ +1 kWh, uma vez por tomada e dia: `alerts.alert_raised` `kind=anomaly` (`warning`) → `peak_alert` só para os moradores (o senhorio não vê gastos diários) | IMPLEMENTADO |
| Lâmpada do orçamento (ALERT-06, `contracts.billing.budget_light`): `BudgetStatus.light` = verde < 80 %, âmbar (`amarelo` de `CORES`) a 80 %, vermelho a 100 %, com `label` em texto (não depende só da cor); sem orçamento ou gasto desconhecido → `null`, nunca verde por omissão. Só para a lâmpada do **próprio quarto** (nunca a de uma zona comum: o orçamento é pessoal) | IMPLEMENTADO (cor na API/app) |
| Escrita da cor na lâmpada real (MCP `color_rgb`) | Não é automática: só via ação proposta com capability verificada, grant (MCP-04) e autorização humana; efeito físico não se afirma só com ACK | PLANEADO |
| Quartos frios (ALERT-06, `features/billing/comfort.py`, migração `0120`): consumidor `billing.cold_rooms` de `sensor.reading_recorded` (só temperatura `ok` com quarto `bedroom`; `unknown`/`stale`/sem quarto/sala ignorados). Guarda só o agregado da noite (22:00–08:00, fuso da casa); noite fria = média < 18 °C; ≥ 3 noites frias nas últimas 7 completas → `alerts.cold_room` para o inquilino do quarto, uma vez por janela. Consumidor P3 `notifications.cold_room` → `comfort_alert` pessoal (nunca senhorio), sem valores de plafond (aviso «ainda tens X kWh do plafond»: PLANEADO) | IMPLEMENTADO |
| Plafond solidário de aquecimento (BILL-03, `features/billing/allowance.py`, migração `0106`): ver «Plafond solidário» abaixo | IMPLEMENTADO |
| Contestar e reemitir (BILL-06, `features/billing/contestations.py`, migração `0130`): o inquilino contesta o **próprio** recibo (opcionalmente um consumo atribuído a si; uma aberta por fatura); só o senhorio decide, sempre com justificação. Rejeitar não muda nada. Aceitar passa o consumo contestado para a conta comum (`manual`, auditado com o senhorio como autor; nunca pior do que a divisão igual), corrige opcionalmente os dados da fatura e **reemite sempre como nova revisão** (a anterior fica `superseded`), guardando o antes/depois da parcela. Correções diretas (`/revisions`) levam as contestações abertas para a nova revisão. O senhorio vê quarto, motivo e decisão, nunca o consumo nem presença. `billing.contestation_changed` → consumidor P3 `notifications.contestation` (aberta: aviso aos senhorios sem o motivo; decidida: aviso a quem contestou com justificação e antes/depois). Respostas tardias a «de quem é esta conta?» não mudam faturas fechadas (o atribuidor ignora-as após o prazo). **App (página Faturas):** o inquilino contesta o recibo («Não concordo com este recibo») ou um consumo na explicação («Este consumo não é meu») e vê o estado e a decisão; o senhorio vê a lista e aceita/rejeita com justificação. Corrigir os dados da fatura ao aceitar (`bill`) só pela API | IMPLEMENTADO |
| Previsão (ALERT-02) | PLANEADO |

Validação da fatura (PROPOSTA de limiares, ajustáveis em `bills.py`): preço médio 0,01–1,00 €/kWh (apanha erros de unidades), período ≤ 62 dias e já terminado, tarifa declarada opcional que tem de fechar com `total − fixa` (folga de 1 %, mínimo 5 cêntimos). Foto/PDF lido por LLM fica para depois e passará pela mesma pré-visualização.

## Ficheiros novos previstos

`features/billing/{attribution,attributor,allocation,bills,closing,budgets,explanation,router,tests}`, `features/budgets/`, `features/alerts/`, `contracts/billing.py`.

## Dependências

P1 (consumo), P3 (confirmações e entrega), P5 (casas, base de dados), P2 (presença para C e esquecidos).

## Critérios de aceitação

- Fixtures A, B e C passam; `Σ amount_cents = total_cents` em todas as fixtures e em testes baseados em propriedades.
- `409 bill_finalized` ao finalizar duas vezes; `422 bill_inconsistent` se `Σ kWh > total`.
- Uma resposta «É minha» cria nova `Attribution` e marca a anterior `superseded`; nada se apaga.
- Senhorio recebe só totais por quarto; inquilino recebe só o seu recibo.
- Notificação de orçamento enviada uma vez por limiar.

## Testes

Puros, com relógio simulado e sem rede/hardware: fixtures, regra A/B/C, prazo de 24 h, saída a meio do mês, resíduo negativo, arredondamento, permissões.

## Plafond solidário de aquecimento (BILL-03)

**IMPLEMENTADO.** O aquecimento básico de cada quarto é pago por todos; só o excesso é individual (v5.1 §8). Premissas:

| Premissa | Regra |
|---|---|
| Limite | `room.included_wh` por **mês** e por quarto, definido pelo senhorio ao criar o quarto. Aparece no `RoomView` e na página da casa, por isso é visível antes da adesão. |
| Período da fatura | Proporcional por mês de calendário: (dias do período nesse mês ÷ dias do mês) × X, somado e arredondado para baixo ao Wh. Novembro inteiro = X; outubro + novembro = 2X. |
| Prova de aquecimento | O aparelho tem de estar identificado (assinatura com vencedor) e registado no catálogo com a categoria `heating`. Tem de ser medido numa tomada do **próprio** quarto e estar atribuído ao seu morador. Um aparelho não identificado ou ambíguo, um aquecedor na sala ou um consumo noutro quarto **não** contam. A explicação do recibo di-lo, nunca em silêncio. |
| Ordem | O plafond enche por ordem cronológica dos consumos (empates pelo id). |
| Repartição | Os Wh cobertos saem da linha `room` do morador e entram numa linha `heating_allowance` («Plafond solidário de aquecimento (parte igual)»), dividida por igual por todos os moradores, com a mesma proveniência do consumo. O total da fatura fecha ao cêntimo como antes. |
| Auditoria | No fecho guardam-se o limite de cada quarto (`billing_allowance`) e, por consumo, `heating`/`covered_wh` em `billing_allocation_item`. Faturas fechadas antes ficam como foram fechadas. |
| Orçamento (ALERT-01) | O gasto do mês aplica o mesmo plafond, e a parte igual do plafond conta em `shared_cents`. |

Exemplo do PDF (v5.1 §20, teste `test_exemplo_do_pdf_excesso_de_330_kwh`): fatura de 120 € (24 € fixos + 600 kWh × 0,16 €), 4 moradores, aquecedor da Ana com 360 kWh no quarto e plafond de 30 kWh. Resultado:
- linha do quarto da Ana: 330 kWh = **52,80 €**;
- linha `heating_allowance`: 7,5 kWh = 1,20 € para cada morador;
- total da Ana: 69,60 €; total de cada um dos outros: 16,80 €.

**PLANEADO:** o aviso privado «ainda tens X kWh do plafond» junto do alerta de quarto frio; e quem pode alterar `included_wh` depois de criado o quarto, e com que efeito (só nas faturas seguintes).

