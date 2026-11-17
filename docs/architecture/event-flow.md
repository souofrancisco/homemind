# Fluxo de eventos

**IMPLEMENTADO**: barramento persistente, idempotência e replay (§4–§5; `core/events.py`), P3 notifications, funções puras de P4 e adaptadores HOUSE-04 na branch #145. **PLANEADO**: handlers BILL-02 que ligam consumos, votos, atribuições e expiração em runtime. Eventos e payloads em [contracts.md](contracts.md); entidades em [data-model.md](data-model.md).

## 1. Fluxo geral

```mermaid
flowchart LR
  MCP["MCP / FakeHome / simulador"] -->|"EnergyReading"| E["energy (P1)"]
  CAM["Câmara na porta"] -->|"DoorCrossed"| P["presence (P2)"]
  APP["Aplicação"] -->|"registo, respostas"| N["notifications (P3)"]

  E -->|"consumption_closed"| B["billing (P4)"]
  P -->|"presence.changed"| B
  E -->|"consumption_detected (dono), sensor.reading_recorded"| P
  P -->|"presence.confirmation_needed, safety.alert_raised"| N
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

Fluxo planeado do PDF §6.5, agora na aplicação (D-01): o aquecedor do Bruno liga-se na sala e a Carla usa-o. BILL-02 ainda não instala os handlers deste fluxo.

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
  E->>B: energy.consumption_closed
  B->>B: HOUSE-04 seleciona a política temporal e avalia evidência/localização
  B->>B: se transição temporal divide o episódio e não há energia segmentada, mantém pending
  B->>N: confirmation_needed (event_id, custo estimado)
  N->>U: notification.created com ações mine/everyone/unknown/other
  U->>N: cada inquilino elegível envia um voto
  N->>N: persiste cada voto por CAS e calcula confirmation_outcome (D-32)
  N->>B: um notification.responded por voto, com outcome cumulativo
  B->>B: HOUSE-04 só mapeia outcome decisivo; votos intermédios mantêm pending
  B->>B: P4 persiste uma Attribution ativa e calcula/reconcilia a fatura
  Note over B: Ao prazo P4 lê Notification.outcome(now) de P3; everyone expirado → fallback igual
```

Regras:

- **Votação (D-32):** cada inquilino elegível do snapshot P3 vota uma vez. Um «É minha» fecha (paga quem assumiu). «É de outra pessoa» (`other` + alvo) só decide quando **pelo menos metade** dos elegíveis (arredondado para cima) escolheu o mesmo alvo; se o próprio assumir antes, fecha com ele. Todos votaram sem decisão, ou 24 h sem decisão → **por todos**. Fonte única: `confirmation_outcome`.
- Cada voto emite `notification.responded` com `outcome`; billing só cria a `Attribution` quando `outcome.decided`. No timeout, `Notification.outcome(now)` de P3 fornece `everyone`; P4 aplica o fallback HOUSE-04. Ainda não há handler/scheduler BILL-02 a executar este fluxo.
- «Não sei» e «É de todos» contam como votos (para «votaram todos»), mas não decidem sozinhos.
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

- **Arredondamento:** método do maior resto sobre `valor_i` em cêntimos; o resto distribui-se, um cêntimo de cada vez, pelas maiores partes fracionárias; empates resolvem-se por sorteio reproduzível (D-34: hash da casa, do mês da fatura e do morador; o mesmo mês dá sempre o mesmo resultado). `Σ amount_cents = total_cents` é invariante testada.
- **Plafond solidário** (prioridade P1): os primeiros `N` kWh de aquecimento básico de cada quarto saem de `individual_kwh` e entram no resíduo.
- **Bi-horário** (P2): o preço passa a depender da hora de cada `ConsumptionEvent`.
- Exemplos numéricos de teste (ambos de 120 €) em [modules/billing.md](../modules/billing.md).

## 4. Semântica do barramento — IMPLEMENTADA (`core/events.py`)

**Entrega pelo menos uma vez, com efeitos idempotentes.** Nunca «exactly once» de ponta a ponta.

```text
produtor → EventBus.publish → INSERT domain_event (seq) → COMMIT → acorda os consumidores
consumidor: loop próprio lê o que ainda não processou (por seq)
   BEGIN IMMEDIATE
     INSERT processed_event(consumer, event_id)   -- PK: duplicado ⇒ ignora (efeito não repete)
     handler(conn, evento)  → efeito + eventos de seguimento (gravados na mesma transação)
   COMMIT                                          -- se o handler levantar: ROLLBACK de tudo
```

| Garantia | Como |
|---|---|
| Persistir antes de entregar | O evento só existe após o COMMIT; um consumidor lê-o da base, não de uma fila em memória |
| Idempotência | `processed_event(consumer, event_id)` com chave única guarda **todos** os ids (não só o último). O efeito e o registo estão **na mesma transação**: não há «efeito feito mas não registado» nem o contrário. Reentregar (`bus.deliver`) devolve `False` sem repetir o efeito. Republicar um evento com o mesmo `id` e conteúdo devolve o gravado; com conteúdo diferente é `EventConflictError` |
| Atomicidade dos seguimentos | Os eventos que o handler devolve gravam-se na mesma transação (padrão *outbox*) e só se entregam depois do COMMIT |
| Handlers | **Síncronos**, rápidos, `(conn, StoredEvent) -> eventos | None`, a correr numa thread com o lock da base. Sem I/O externo dentro do handler (WS, HTTP, MCP): usar eventos de seguimento e um consumidor próprio |
| Falha | Tentativas limitadas (`max_attempts`=5) com *backoff* linear; `event_failure` regista tentativas e **só o tipo** do erro; ao esgotar fica `dead` para esse consumidor e deixa de o bloquear. Uma linha guardada que já não valida (contrato apertado, base de dev antiga) falha **por evento** e vai para `dead`; o consumidor nunca morre em silêncio (erro de ciclo ⇒ log do tipo + espera + continua). Um consumidor nunca afeta outro nem o produtor |
| Reinício | Nada a recuperar: o que não está em `processed_event` continua pendente. Reinício entre a gravação e a entrega, ou a meio do handler, é seguro |
| Ordem | `seq` global e único (atribuído pela base). Cada consumidor recebe por `seq`, mas um evento em *retry* pode ser ultrapassado: os handlers têm de tolerar chegadas fora de ordem (comparar `seq`/`ts` do estado que alteram). `correlation_id` agrupa um fluxo e **não ordena** |
| Dois produtores | `publish` serializa no lock; `publish_threadsafe` serve produtores fora do loop (visão). `seq` único e crescente (testado com 4 threads) |
| Shutdown | `stop()` cancela os consumidores; uma transação em curso termina ou faz ROLLBACK; a base fecha depois. Eventos pendentes ficam para o arranque seguinte |
| Consumidor novo | Um nome nunca visto processa **todo** o histórico dos seus tipos (ou desde `since_seq`). Renomear um consumidor reprocessa tudo: o nome é a chave de idempotência |
| Privacidade | Só `data` tipado (`extra=forbid`); sem frames, imagens, tokens nem ids externos; `event_failure` nunca guarda mensagens |
| Simulado vs real | `provenance.origin` em cada evento (`domain_event.origin`); uma casa `real` recusa eventos simulados |

Como um módulo subscreve (no `lifespan` do seu router, depois de o core arrancar): `app.state.bus.subscribe("billing.attributor", handler, ["notification.responded"])`. O barramento está em `app.state.bus`; a base de dados em `app.state.db`.

## 5. Replay e verificação de idempotência

`load_events(conn)` lê `StoredEvent` por `seq`; `replay(events, bus)` republica-os (mesmos ids) **numa base isolada** (`Database(":memory:")` ou ficheiro temporário + `migrate` + a casa `demo`). Repetir o replay não duplica nada (testado). Eventos simulados nunca entram numa casa `real`. Para repetir um cenário: criar base nova, `seed_demo`, subscrever os consumidores, `replay`; para provar idempotência, repetir o `replay` e comparar `processed_event`. **Nunca** reproduzir sobre a base real de uma casa `demo` em uso sem limpar `processed_event` e as tabelas derivadas.
