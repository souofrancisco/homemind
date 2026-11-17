# Fluxo de eventos

**PLANEADO.** Eventos e payloads em [contracts.md](contracts.md); entidades em [data-model.md](data-model.md).

## 1. Fluxo geral

```mermaid
flowchart LR
  MCP["MCP / FakeHome / simulador"] -->|"EnergyReading"| E["energy (P1)"]
  CAM["Câmara na porta"] -->|"DoorCrossed"| P["presence (P2)"]
  APP["Aplicação"] -->|"registo, respostas"| N["notifications (P3)"]

  E -->|"consumption_detected"| B["billing (P4)"]
  P -->|"presence.changed"| B
  B -->|"confirmation_needed"| N
  N -->|"notification.created (WS)"| UI["Aplicação"]
  UI -->|"respond"| N
  N -->|"notification.responded"| B
  B -->|"attribution_changed"| N
  B -->|"threshold_crossed / alert_raised"| N
  B -->|"bill_finalized"| N
  A["agent (P3)"] -->|"ações confirmadas"| H["devices / Home (P1)"]
  N --> A
```

Cada seta é um evento do barramento em processo, gravado em `domain_event`. Os módulos só se conhecem pelos contratos.

## 2. Confirmação de um consumo

Exemplo do PDF §6.5, agora na aplicação (D-01): o aquecedor do Bruno liga-se na sala e a Carla usa-o.

```mermaid
sequenceDiagram
  autonumber
  participant T as Tomada (MCP/simulador)
  participant E as energy (P1)
  participant B as billing (P4)
  participant N as notifications (P3)
  participant U as Aplicação da Carla
  T->>E: leituras de potência
  E->>E: degrau +2000 W, assinatura «aquecedor do Bruno» (confiança 0,9)
  E->>B: consumption_detected (location=common, owner=Bruno)
  B->>B: regra da casa = «perguntar» e custo acima do limiar
  B->>N: confirmation_needed (event_id, custo estimado)
  N->>U: notification.created «De quem é esta conta?» [É minha] [É de todos] [Não sei]
  U->>N: respond(action_id = mine)
  N->>N: guarda resposta (autor e hora), status = actioned
  N->>B: notification.responded
  B->>B: Attribution(resident=Carla, method=confirmation), anterior = superseded
  B->>N: attribution_changed → notificação de confirmação «Registado na tua conta»
  Note over B: Sem resposta em 24 h → fallback da regra da casa (por igual ou por presença), Attribution(method=equal_fallback)
```

Regras:

- Pode responder qualquer **inquilino ativo da casa**; a primeira resposta válida fixa a atribuição; uma resposta posterior em sentido contrário **não** a altera: cria um pedido de contestação visível para a casa (**PROPOSTA**, P-03).
- «Não sei» mantém o pedido aberto até ao fim do prazo; depois aplica-se o fallback.
- «É minha» é limitado: o morador só pode atribuir a si ou à conta comum, nunca a um terceiro.
- Em `HOME_BACKEND=fake` ou com leituras `simulated`, a atribuição resultante é `simulated` e a notificação diz-o.

### Estados do consumo e da notificação

```mermaid
stateDiagram-v2
  [*] --> detected
  detected --> identified: assinatura reconhecida
  detected --> unknown: sem correspondência
  identified --> attributed: regra de quarto (sem pergunta)
  identified --> pending_confirmation: zona comum e custo acima do limiar
  unknown --> pending_confirmation
  pending_confirmation --> attributed: resposta «minha» ou «de todos»
  pending_confirmation --> expired: prazo sem resposta
  expired --> attributed: fallback da regra da casa
  attributed --> contested: contestação
  contested --> attributed: revisão
```

```mermaid
stateDiagram-v2
  [*] --> unread
  unread --> read: aberta
  unread --> actioned: ação escolhida
  read --> actioned: ação escolhida
  unread --> expired: prazo
  read --> dismissed: dispensada
  actioned --> [*]
  expired --> [*]
  dismissed --> [*]
```

## 3. Cálculo da fatura

Algoritmo determinístico e testável (sem LLM). Todos os valores em cêntimos inteiros; kWh em `float`.

```mermaid
flowchart TD
  A["Entrada: total_cents, fixed_cents, total_kwh, período, memberships ativas"] --> B["energy_cents = total_cents − fixed_cents"]
  B --> C["preço = energy_cents ÷ total_kwh"]
  C --> D["Somar kWh das Attributions ativas por morador (por proveniência)"]
  D --> E{"Há consumo na conta comum?"}
  E -->|"sim"| F["Repartir pela regra da casa: igual (A), pedido já respondido (B) ou por presença (C)"]
  E -->|"não"| G["individual_kwh = kWh próprios"]
  F --> G
  G --> H["resíduo_kWh = total_kwh − Σ individual_kwh"]
  H --> I{"resíduo ≥ 0 ?"}
  I -->|"não"| X["Erro bill_inconsistent (kWh atribuídos > fatura)"]
  I -->|"sim"| J["base = fixed_cents + resíduo_kWh × preço"]
  J --> K["base por morador = base ÷ nº de moradores (opção: ponderar por dias)"]
  K --> L["valor_i = individual_kWh_i × preço + base_i"]
  L --> M["Arredondar pelo maior resto: Σ valor_i = total_cents"]
  M --> N["Recibo por morador: linhas, proveniência (medido/estimado/inferido/simulado), botão contestar"]
```

Notas:

- **Arredondamento:** método do maior resto sobre `valor_i` em cêntimos; o resto distribui-se, um cêntimo de cada vez, pelas maiores partes fracionárias; empates resolvem-se por `resident_id` (determinístico). `Σ amount_cents = total_cents` é invariante testada.
- **Plafond solidário** (prioridade P1): os primeiros `N` kWh de aquecimento básico de cada quarto saem de `individual_kwh` e entram no resíduo.
- **Bi-horário** (P2): o preço passa a depender da hora de cada `ConsumptionEvent`.
- Exemplos numéricos de teste (ambos de 120 €) em [modules/billing.md](../modules/billing.md).

## 4. Garantias dos consumidores de eventos

| Garantia | Como |
|---|---|
| Idempotência | Cada consumidor regista **todos** os `event.id` processados na mesma transação do efeito (tabela `processed_event(consumer, event_id)`, chave única); um id já visto é ignorado. Guardar só o último id **não** chega: um replay ou entrega fora de ordem repetiria efeitos |
| Ordem | `correlation_id` **só agrupa** eventos do mesmo fluxo, não os ordena. A ordem vem de `seq`, número crescente atribuído pelo barramento ao gravar em `domain_event` (único, global), usado para ordenar replays e consultas. Em entrega, a ordem só é garantida entre eventos do mesmo tipo e produtor; os consumidores têm de tolerar chegadas fora de ordem (comparar `seq` ou `ts` do estado que alteram e ignorar o mais antigo) |
| Falha | Um handler que falha é registado (tipo de erro, sem dados pessoais) e não afeta os outros |
| Replay | Para a demo e para testes, **sempre numa base de dados isolada ou com o estado dos consumidores reposto** (limpar `processed_event` e as tabelas derivadas); reproduzir sobre a base real seria ignorado pela idempotência ou duplicaria efeitos. Os eventos reproduzidos levam `provenance=simulated` e novo `correlation_id` |
