# Módulos `billing`, `budgets` e `alerts` — atribuição, fatura, orçamentos e alertas

**Dono: P4 (Amorim3000).** **PLANEADO.** Algoritmo e diagrama: [event-flow.md](../architecture/event-flow.md) §3. Entidades: [data-model.md](../architecture/data-model.md).

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

## Regras da conta comum (PDF §6.2)

| Opção | Comportamento | Prioridade |
|---|---|---|
| **A — por igual** | O consumo comum divide-se por todos os moradores ativos | P0 |
| **B — perguntar** (recomendada pelo PDF) | Cria pedido na aplicação; sem resposta no prazo (omissão 24 h) cai em A (ou C) | P0 |
| **C — por presença** | Divide pelos que estavam em casa (usa presença de P2) | P1 |

Só se pergunta acima de um custo estimado (omissão 0,50 €, valor do PDF «por exemplo»); abaixo vai direto para a conta comum. A omissão `ask` e os valores são configuráveis em `Household` e **PROPOSTAS** (ver [decisions.md](../decisions.md) P-03).

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

**Fixture C — arredondamento:** 100,00 € repartidos por 3 moradores iguais → 33,34 / 33,33 / 33,33 (o cêntimo vai para o `resident_id` menor).

## Orçamentos (P0 → P1)

- Orçamento pessoal: limiares 50 / 80 / 100 % (omissão do PDF), notificação por limiar **uma só vez** por período (`last_threshold_notified`).
- O gasto comparado é o **consumo individual acumulado × preço** (sem a base fixa): **PROPOSTA** a confirmar (P-10).
- Previsão do fim do mês: projeção linear do gasto acumulado (P1). Algoritmos mais complexos ficam fora do MVP.
- Plafond por quarto do senhorio (`included_kwh`): aviso antes de passar e quando passa; o excesso paga o próprio quarto (PDF §6.9, §15.3) — P1.

## Alertas (P1/P2)

| Alerta | Gatilho (PDF §6.9) | Prio |
|---|---|---|
| Pico em zona comum | > 1,5 kW durante > 30 min, ou conta da sala do dia > 2× a média | P1 |
| Aparelho esquecido | Aparelho grande ligado com o dono fora há > 1 h (precisa de presença) | P2 |
| Não bate certo | Assinatura do aparelho de um morador fora do quarto dele; consumo noturno anormal | P2 |

Todos produzem `alerts.alert_raised`; o módulo `notifications` decide destinatário (pessoal ou da casa) e entrega.

## Ficheiros existentes reutilizáveis

Nenhum de domínio. Reaproveitar o padrão de feature (`router.py`, `tests/`), `core/errors.py`, o relógio injetado dos testes do motor antigo (`features/engine/tests/`) e `TARIFA_EUR_KWH` de `core/config.py`.

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
