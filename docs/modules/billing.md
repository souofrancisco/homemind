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
- Plafond por quarto do senhorio (`included_kwh`): aviso antes de passar e quando passa; o excesso paga o próprio quarto (PDF §6.9, §15.3) — P1.

## Alertas (P1/P2)

| Alerta | Gatilho (PDF §6.9) | Prio |
|---|---|---|
| Pico em zona comum | > 1,5 kW durante > 30 min, ou conta da sala do dia > 2× a média | P0 (ALERT-03 #102) |
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
| Entrada da fatura (BILL-01): `BillIn` → pré-visualização → rascunho em `billing_bill` (migração `0100`), `billing.bill_created`, leitura por papel | IMPLEMENTADO (`features/billing/{bills,router}.py`) |
| Fecho do mês (BILL-04, `features/billing/closing.py`, migração `0102`): finalizar (parcelas imutáveis, Σ = total ao cêntimo, `409` ao repetir), correções por revisão (a anterior fica `superseded`), resumo do senhorio por quarto e recibo do inquilino | IMPLEMENTADO |
| Orçamento pessoal e avisos 50/80/100 % (ALERT-01, `features/billing/budgets.py`, migração `0103`): gasto com todos os custos (D-31), desconhecido sem preço, um aviso por limiar e ciclo (ao saltar vários avisa só o mais alto), reset explícito ao redefinir; reavaliado em cada atribuição, fecho de fatura e a cada 60 s. `alerts.threshold_crossed` → aviso pessoal (consumidor `notifications.budget_threshold`) | IMPLEMENTADO |
| Plafond por quarto (BILL-03), previsão (ALERT-02), picos (ALERT-03), contestação (BILL-06) | PLANEADO |

Validação da fatura (PROPOSTA de limiares, ajustáveis em `bills.py`): preço médio 0,01–1,00 €/kWh (apanha erros de unidades), período ≤ 62 dias e já terminado, tarifa declarada opcional que tem de fechar com `total − fixa` (folga de 1 %, mínimo 5 cêntimos). Foto/PDF lido por LLM fica para depois e passará pela mesma pré-visualização.

## Ficheiros novos previstos

`features/billing/{attribution,allocation,receipt,router,tests}`, `features/budgets/`, `features/alerts/`, `contracts/billing.py`.

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
