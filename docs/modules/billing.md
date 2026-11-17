# Módulos `billing`, `budgets` e `alerts` — atribuição, fatura, orçamentos e alertas

**Dono: P4 (Amorim3000).** **PARCIALMENTE IMPLEMENTADO** (ver «Estado»); o resto é **PLANEADO**. Algoritmo e diagrama: [event-flow.md](../architecture/event-flow.md) §3. Entidades: [data-model.md](../architecture/data-model.md).

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
| Votação da regra B (D-32) | IMPLEMENTADO no contrato (`confirmation_outcome`); consumo do `outcome` em billing: PLANEADO |
| Entrada da fatura (BILL-01): `BillIn` → pré-visualização → rascunho em `billing_bill` (migração `0100`), `billing.bill_created`, leitura por papel | IMPLEMENTADO (`features/billing/{bills,router}.py`) |
| Fecho e persistência das alocações (BILL-04), orçamentos, alertas | PLANEADO |

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
## Contrato de políticas HOUSE-04 #87 (adaptador implementado no PR #145; handlers BILL-02 planeados)

HOUSE-04 **resolve a política**; P4 **materializa a atribuição** e faz todos os
cálculos da fatura real. Usar `contracts.policy.PolicyDecision` com `status`,
`reason`, `policy_version`, `target_type`, `target_resident_id`, `method`
e `provenance`. Uma `PolicyDecision(status='pending')` **nunca** gera
`Attribution` ativa individual nem uma dívida individual.

`AttributionMethod.equal_rule` distingue a aplicação automática da regra
A de `AttributionMethod.equal_fallback` (B expirou). `room_rule` vem do
contrato temporal do quarto; `confirmation` vem do `ConfirmationOutcome`
decisivo de P3 (`self_claimed`, maioria `accusation_accepted`, ou `everyone`).
O proprietário do aparelho não é o pagador, nem um medidor agregado prova
onde está o aparelho. P4 recebe `location_verified` de HOUSE-03;
não inferir `True` a partir de `Device.room_id` ou de uma assinatura.

Votos intermédios, incluindo `unknown`, conservam `pending`. D-32 resolve
`mine` com um voto, `other` com pelo menos metade para o mesmo alvo, e
`everyone` quando todos votam sem atingir esse limiar. Ao prazo, P3 devolve
`Notification.outcome(now)=everyone`; P4 passa esse resultado ao adaptador
HOUSE-04, que grava `fallback/common/equal_fallback`. O fallback F1 é igual
e fica no snapshot da política. Falta de localização,
ocupante ou custo conhecido permanece pendente; o resíduo será explicitamente
tratado em BILL-02, nunca desaparece silenciosamente. C por presença é F2.

P4 pode consumir `resolve_and_store`, `record_confirmation_outcome`,
`expire_and_store`, `confirmation_intent` e `as_attribution` como descrito
em [households.md](households.md), com transações do `core/events.py`.
HOUSE-04 não grava votos, atribuições, partes financeiras nem tabelas de
resposta. BILL-02 é responsável pela persistência de atribuições ativas e
pela decisão única por consumo; o registo de decisão HOUSE-04 é apenas a
auditoria da política aplicada.

**Implementado em P4:** funções puras `features/billing/attribution.py::decide`
e `features/billing/allocation.py::allocate`, `shares_from_attributions`,
maior resto, reconciliação exata e desempate reproduzível D-34.
**Ainda PLANEADO em BILL-02:** handlers persistentes reais
`energy.consumption_closed` e `notification.responded`, agendamento de
expirações, publicação `billing.attribution_changed`, revisão/contestação e
integração em runtime com HOUSE-04. Quando ligado, o caminho temporal usa
HOUSE-04 como fonte da política; `decide` legado não deve ser invocado para
o mesmo consumo.
