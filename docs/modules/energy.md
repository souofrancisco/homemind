# Módulo `devices` + `energy` — dispositivos, leituras e assinaturas

## Localização e cobertura (ENERGY-05)

**IMPLEMENTADO nesta tarefa**, sem hardware nem rede. `locate.py` é puro e usa apenas
`DeviceLocation(role, room_id, room_kind)`, obtido pelo novo método de leitura
`ApplianceCatalog.device_location(conn, household_id, device_id)`. O adapter SQLite
isola dispositivo e divisão pela casa; uma divisão ausente/desconhecida não é prova.

- `room` exige tomada `room_meter`, `room_id` e divisão `bedroom`.
- `common` exige `device.room_id` de uma divisão `common`, exceto `main_meter`.
- `main_meter` é sempre agregado e fica `unknown`, mesmo configurado numa divisão
  ou com aparelho identificado. Sem divisão, tipo de divisão conhecido ou dispositivo,
  fica igualmente `unknown`, com `room_id=None`. Nunca se assume um quarto por omissão.
- O tracker fixa a localização da **tomada** na abertura da sessão e conserva-a no
  fecho e nos ciclos de termóstato. Mudanças posteriores de configuração não movem
  retroativamente o consumo. Sem callback/catálogo conserva o comportamento `unknown`.
- O consumidor consulta o catálogo na conexão/transação do handler e restaura os
  callbacks no `finally`; não guarda conexão nem cache de configuração entre handlers.
  A cache já existente de eventos por entrega continua a garantir o replay de resultados.
- `ConsumptionSessionView.declared_room_id` é apenas a pista declarada do aparelho
  identificado, obtida com `ownership_at` no instante de início. Sem identificação,
  catálogo ou ownership válido é `None`. Nunca preenche `ConsumptionEvent.location`.

`GET /api/households/{household_id}/energy/overview` acrescenta `coverage`:

| Campo | Significado |
|---|---|
| `period_start`, `period_end` | Início do mês no fuso da casa (expresso em UTC), até `now` |
| `total_wh` | Soma sample-and-hold por tomada, sobre leituras utilizáveis consecutivas |
| `measured_wh` | Wh das sessões `room` ou `common` |
| `inferred_wh` | Wh das sessões `unknown` com `match.appliance_id` |
| `unattributed_wh` | Diferença para o total: base, desconhecidos e resíduo |
| `measured_percent`, `inferred_percent`, `unattributed_percent` | Percentagens inteiras reconciliadas |
| `status` | `no_data` se o total arredondado for zero; nesse caso todos os valores são zero |
| `adjusted` | Sessões excederam o total integrado e foi necessário reconciliar |
| `provenance` | Proveniências das leituras que suportam o total, incluindo `simulated` |

Decisões explícitas de cálculo:

- A cobertura consulta todo o histórico; os limites existentes de 500 eventos/20
  sessões continuam apenas nas listas recentes. Considera a última versão de cada
  sessão até `now`, excluindo descartadas e energia ausente; não duplica abertura/fecho.
- Usa `observed_at` (senão `ts`), rejeita polls/observações repetidos ou atrasados como
  ENERGY-02. `missing`, `stale` e `unit_unknown` interrompem a integração: não conta nem
  o intervalo até à lacuna nem até à recuperação. Não prolonga a última leitura até
  `now`; só intervalos delimitados por duas leituras boas suportam energia.
- Recorta intervalos no início do mês; inclui a leitura anterior para delimitar a
  meia-noite. Não usa leituras nem versões de sessões posteriores a `now`.
- As sessões só persistem Wh acumulados. Quando atravessam o mês, os Wh são rateados
  pela duração sobreposta (aproximação temporal explícita, não uma medição horária).
  Sessões em curso só contam o snapshot publicado, sem extrapolação até `now`.
- Acumula em `Decimal`; o total é arredondado uma vez a Wh, com empate para o par,
  como ENERGY-02. Distribui Wh inteiros pelo método dos maiores restos. Se as sessões
  excederem o total (arredondamento ou sobreposição), reduz medido/inferido na mesma
  proporção, deixa resíduo zero e assinala `adjusted=true`. Nunca há resíduo negativo.
- As percentagens usam os Wh finais e maiores restos para fechar exatamente em 100 %;
  empates seguem medido, inferido, não atribuído. Total zero dá 0 % em todas as parcelas.
- O total soma as tomadas observadas, como pedido; não é o contador da fatura nem
  elimina possível sobreposição física entre contadores agregados e subordinados.

O RBAC existente mantém-se: apenas moradores com âmbito `household`; senhorio e
operador não recebem curvas, horários, leituras, sessões nem a nova cobertura.
Billing e os contratos dos eventos de consumo mantêm-se inalterados. Os testes novos
usam dados **SIMULADOS** e ficam para execução pelo utilizador; nesta tarefa só se
executam `uv run ruff check .` e `uv run ruff format --check .`.

**Dono: P1 (brunovieira88).** **PLANEADO**, sobre código existente em `connectors/`. Integração MCP: [integrations/altice-mcp.md](../integrations/altice-mcp.md).

**HOUSE-03:** o catálogo e as suas interfaces SQLite estão implementados na branch do PR #142;
continuam fora da `main` até integração. Isso não implementa o pipeline P1 descrito abaixo.

## Responsabilidade

1. Falar com o kit (MCP) ou com o FakeHome/simulador e produzir `EnergyReading` com proveniência.
2. Detetar degraus de potência e episódios de consumo.
3. Identificar o aparelho por assinatura (com confiança), localizar (quarto ou zona comum) e emitir `ConsumptionEvent`.
4. Executar ações físicas autorizadas (corte da tomada, cor da lâmpada) pelo contrato `Home`.

## Recebe / produz

| Recebe | Produz |
|---|---|
| Polling do MCP (a cada 5 s, já implementado) ou do simulador | `EnergyReading`, `energy.reading_recorded` |
| Aparelhos registados e assinaturas (UI/API) | `PowerStep`, `energy.step_detected` |
| Respostas de confirmação (para aprender) | `ConsumptionEvent`, `energy.consumption_detected`, `energy.consumption_closed` |
| Respostas a «O que é este aparelho?» (`notification.responded`, ENERGY-04) | `energy.identification_needed` (ENERGY-04) |
| Ordens de ação confirmadas (agente, automações) | Escritas via `Home` com a whitelist atual |

## Pipeline (PDF §6.3, adaptado)

| Passo | Implementação inicial | Prioridade |
|---|---|---|
| Registo de aparelhos (nome, dono, âmbito, potência típica) | API + formulário | P0 |
| Deteção de degraus | Diferença entre janelas de leituras, limiar configurável; ΔW mínimo (PDF sugere > 300 W para a demo) | P0 |
| Identificação | Vizinho mais próximo sobre (potência, duração, padrão), devolve `confidence` e candidatos; abaixo do limiar → `unknown` | P0 |
| Localização | P1 observa `ConsumptionEvent.location`/`room_id`. `ApplianceOwnership.home_room_id` e `Device.room_id` são locais habituais/configurados, não prova da utilização efetiva. Uma tomada agregada pode não localizar uma carga individual | P0 |
| Aprendizagem com confirmações | Atualiza `ApplianceSignature` (`origin=learned`) — **IMPLEMENTADO** (ENERGY-04) | P1 |
| Aparelhos desconhecidos recorrentes (clustering) | Agrupar sessões semelhantes e perguntar uma vez — **IMPLEMENTADO** (ENERGY-04) | P2 |
| Estimativa de lâmpada (9 W × tempo × brilho) | `provenance=estimated` | P2 |

## Collector MCP → `EnergyReading` (MCP-02) — **IMPLEMENTADO** (sem ligação à app)

Código: `connectors/mcp_energy.py` (`reading_from_device`, função pura) e `connectors/mcp_collector.py` (`EnergyCollector`); ligação opcional ao `McpHome` por `McpHome.coletor`.

- **Estados:** `ok`, `missing`, `unit_unknown` (há valor bruto mas a unidade não é conhecida: nunca se converte), `stale` (último contacto mais antigo que `stale_after`, por omissão 90 s = 3 × o batimento de 30 s da tomada). Ausência de leitura **nunca** é 0; um 0 W é uma leitura válida.
- **Unidade:** a declarada na capability tem prioridade sobre `MCP_INSTANTPOWER_UNIT`; sem nenhuma, `unit_unknown`. `observed_at` vem de `lastCommunicationTime` (epoch em ms).
- **Proveniência:** `real/measured` só em `ok`; nos outros estados `real/estimated` (nenhum valor é de confiança).
- **Deduplicação:** o `McpHome` lê a cada 5 s mas a tomada atualiza de ~30 em ~30 s (e quando a carga muda); o collector só publica `EnergyReadingRecorded` quando (`observed_at`, estado, valor bruto) mudam, e publica **uma vez** a transição `ok → stale`. Falha do MCP (`unavailable()`): esquece a leitura e não publica nada.
- **Resiliência:** uma falha de `publish` é registada (só o tipo) e nunca chega ao `McpHome`; a amostra repete a tentativa na leitura seguinte.
- **Polling:** `MCP_POLL_SECONDS` (por omissão 5, mínimo 1) e backoff exponencial até `MCP_POLL_BACKOFF_MAX_S` (60) após falhas seguidas.
- **Por fazer (PLANEADO):** montar o `EnergyCollector` no arranque da app com o barramento (`app.state.bus`), o `household_id` e o `device_id`. Ainda não existe tabela de dispositivos (HOUSE-03) nem rota para criar casas (HOUSE-01); o barramento recusa eventos de casas inexistentes. O `publish` injetado deve ser não bloqueante quando chamado no event loop.

## Demo web viva — **IMPLEMENTADO**

`features/demo_live` emite leituras a cada 5 segundos na cópia web, com origem `simulated`,
base aproximada de 40 W e sessões de aquecedor (2040 W acima da base) ou chaleira
(1820 W acima da base). O aquecedor inicia sozinho cerca de 60 segundos após o arranque
e dura cerca de 180 segundos; a chaleira dura 155 segundos. No fim da sessão a tomada emite uma
leitura em falta e volta à base, o que fecha o consumo de imediato (sem esperar os 10 min da
pausa de termóstato): o pedido «De quem é esta conta?» surge cerca de 4 minutos após o arranque.
A cópia contém um medidor `room_meter`
SIMULADO na sala para provar localização `common`; não usa o `main_meter` agregado.
`DEMO_LIVE` é verdadeira por omissão em perfil demo e pode ser desligada com
`DEMO_LIVE=false`. `make demo-web-reset` reancora o cenário antes de apresentar.
O emissor só funciona com `PROFILE=demo`, `HOME_BACKEND=fake` e uma casa demo; não acessa
MCP nem executa escritas físicas. A interface identifica estas sessões como **SIMULADO**.

## Degraus e sessões ON/OFF (ENERGY-02) — **IMPLEMENTADO** (sem ligação à app)

Código: `features/energy/steps.py` (`StepTracker`, puro) e `features/energy/consumer.py` (consumidor do barramento para `energy.reading_recorded`). Publica `energy.step_detected`, `energy.consumption_detected` e `energy.consumption_closed`. Valores **decididos pelo utilizador (17/11/2026)**:

| Regra | Valor |
|---|---|
| Degrau | variação ≥ **100 W** face à base (§6.7: abaixo disso vai para o resíduo) |
| Confirmação | na **primeira** leitura que mostra o novo nível (a tomada já só reporta de ~30 em ~30 s e na mudança) |
| Lacunas (`missing`/`stale`/`unit_unknown`) | **sem degrau** através da lacuna; a primeira leitura boa a seguir é a nova base; sem energia durante a lacuna |
| Sessão que já não cabe depois de uma lacuna | fecha com `ended_at` = **última leitura boa antes da lacuna** (subestima, nunca sobrestima) |
| Sessões | `ConsumptionEvent` com aparelho por identificar (`match` vazio) e `location=unknown`; o ENERGY-03/05 preenchem depois |
| Termóstato | por tomada, a mesma carga (±50 W) que volta em ≤ **10 min** continua a mesma sessão |
| Energia | sample-and-hold; com **uma** sessão aberta conta a potência medida acima da base, com **várias** cada uma conta o seu ΔW |
| Várias cargas na mesma tomada | uma descida fecha a sessão de ΔW mais parecido (§6.7); empate: a mais antiga |

**Por fazer (PLANEADO):** subscrever o consumidor no arranque da app (precisa de casa e dispositivos: HOUSE-01/03) e identificar o aparelho (ENERGY-03). O estado do tracker é em memória e reinicia com o processo.

## Identificação do aparelho (ENERGY-03) — **IMPLEMENTADO** (sem ligação à app)

Código: `features/energy/classifier.py` (`classify`, `explain`; puro) integrado no `StepTracker`: os eventos `energy.consumption_detected` (identificação **provisória**: potência e hora) e `energy.consumption_closed` (identificação **final**: potência, duração, padrão e hora) já saem com o `ApplianceMatch` preenchido. O `id` do consumo não muda; o billing guarda a última versão. Valores **decididos pelo utilizador (17/11/2026)**:

| Regra | Valor |
|---|---|
| Algoritmo | vizinho mais próximo pesado; pesos potência 0,5 / duração 0,3 / padrão 0,1 / hora habitual 0,1 (os indisponíveis saem e os restantes renormalizam) |
| Potência | dentro da tolerância: 1 → 0,5; até 2× a tolerância: 0,5 → 0; acima disso não é candidato |
| Sem vencedor | melhor confiança < 0,6 → `unknown` **sem candidatos listados**; dois melhores a menos de 0,15 → `ambiguous` (candidatos listados) |
| Cobrança | sem vencedor não há cobrança individual (segue a regra da zona comum) |
| Aparelhos iguais | se só a hora os distingue, o fecho pode ficar sem vencedor mesmo que o arranque tivesse um: na dúvida não se cobra |
| Dono | com vencedor pessoal, `appliance_owner_resident_id` vem do catálogo (`ownership_at`); `location` continua `unknown` (ENERGY-05) |

A explicação completa por candidato (componentes e pontuação) fica disponível em `explain()` para o recibo.

## Aprendizagem automática de assinaturas (ENERGY-01) — **IMPLEMENTADO**

Código: `features/energy/learning.py` (puro), `learning_consumer.py` (subscrito no arranque da energia como `energy.learning`) e `signatures.py` (rotas incluídas no router da energia). Valores **decididos pelo utilizador (17–18/11/2026)**:

| Regra | Valor |
|---|---|
| Sem cliques | uma sessão fechada só é atribuída a um aparelho pela **tomada associada** (`appliance_meter_link`) ou, numa tomada partilhada, se a potência bate com a `typical_watts` de **um único** aparelho; empate ou nenhum → não aprende |
| Assinatura | uma por aparelho (`stable_id("energy.signature", appliance_id)`), média acumulada, `samples` + 1, `origin=learned` |
| Tolerância | `max(50 W, 10 % da média)` |
| Padrão | `patterns.infer_pattern` (curto / cíclico / decrescente / contínuo); fica o mais frequente; o morador pode corrigir e a correção fica travada |
| Horas habituais | hora local de início (fuso da casa) |
| API | `GET /api/households/{id}/energy/signatures` e `PATCH …/signatures/{appliance_id}` (padrão); senhorio sem acesso, operador sem `typical_hours` |

O contrato do catálogo ganhou `appliances_for_household(conn, household_id, at)` (só leitura; implementado em `features/appliances/repo.py`). Contagens por padrão e travões em `energy_signature_stats` / `energy_signature_lock` (migração `0400`).

## Aprendizagem por confirmação (ENERGY-04) — **IMPLEMENTADO** (backend; a pergunta aparece na lista genérica de notificações da app; desfazer ainda sem UI, **PLANEADO**)

Código: `features/energy/identification.py` (regras puras), `identification_consumer.py` (consumidor `energy.identification`, subscrito no arranque da energia com o catálogo lido tarde de `app.state`), rotas de desfazer em `signatures.py`, migração `0401_energy_identification.sql`. Valores **decididos pelo utilizador (18/11/2026)**:

| Regra | Valor |
|---|---|
| Que sessões | `energy.consumption_closed` fechadas, > 50 W, **sem aparelho nem candidatos** e que a ENERGY-01 também não explica (tomada associada ou potência registada única) |
| Agrupar | por casa (qualquer tomada): potência dentro de `max(50 W, 10 %)` da média do grupo **e** duração semelhante (`min/max >= 0,5`); vários grupos → o de potência mais próxima |
| Quando perguntar | à **3.ª ocorrência em 7 dias**, **uma só vez** por grupo (com pergunta pendente, a 4.ª e a 5.ª não perguntam) |
| Pergunta | `energy.identification_needed` (`ApplianceIdentificationRequest`: potência e duração médias, hora local habitual, n.º de ocorrências, `expires_at` = 24 h) → notificação da casa `appliance_identification` para os inquilinos ativos (nunca o senhorio): «Um aparelho de ~800 W liga muitas vezes por volta das 8h. O que é?» [É meu] [É da casa] [Ignorar] |
| Resposta | qualquer inquilino; a **primeira resposta válida fecha** (não é votação). «É meu» → aparelho **pessoal de quem respondeu**; «É da casa» → aparelho **comum**; nome genérico «Aparelho ~800 W» (« (2)» se repetido), categoria `other`, `typical_watts` = média do grupo (renomeia-se pela API de aparelhos) |
| Assinatura | nasce das sessões do grupo (amostras `confirmation`, `origin=learned`); a sessão parecida seguinte já é identificada pelo classificador e a ENERGY-01 continua a aprender |
| «Ignorar» ou sem resposta | o grupo não volta a perguntar durante **7 dias** (desde a resposta ou desde que a pergunta caducou); depois pode voltar |
| Desfazer | histórico de amostras por evento (`energy_signature_sample`: amostras `learning` da ENERGY-01 e `confirmation`); a assinatura **recalcula-se sempre** a partir das não revogadas. `POST …/energy/identifications/{request_id}/revoke` revoga as amostras dessa resposta (o `request_id` é o `ref.id` da notificação); `POST …/energy/signatures/{appliance_id}/samples/{sample_id}/revoke` revoga uma; `GET …/signatures/{appliance_id}/samples` lista-as (só inquilinos: horas são hábitos). Escrita com as regras do PATCH (dono, ou quem registou um aparelho comum). Sem amostras, a assinatura (com contagens e travão de padrão) é removida e deixa de contar. Leituras, consumos e eventos **nunca** mudam; o aparelho criado mantém-se |

Estado persistido (sobrevive a reinícios) em `energy_identification_group`, `energy_identification_session` e `energy_identification_request`, na transação do barramento e com ids derivados do evento de origem. Assinaturas aprendidas antes da `0401` ficam como base fixa (`energy_signature_baseline`, não revogável) somada às amostras novas.

O contrato do catálogo ganhou `create_learned_appliance(conn, household_id, *, name, typical_watts, ownership, registered_by_resident_id, at)` (HOUSE-03, `features/appliances/repo.py`), com as validações do registo pela API.

## Kit real → barramento — **IMPLEMENTADO** (só com `ENERGY_HOUSEHOLD_ID`)

`features/energy/kit.py` (`attach_kit_collectors`), chamado no arranque do `engine` logo depois de iniciar o `McpHome`, **só** com `HOME_BACKEND=mcp` e `ENERGY_HOUSEHOLD_ID` de uma casa existente (senão não liga nada e regista um aviso sem IDs). Na primeira leitura, a tomada (`main_meter`) e os sensores de contacto e clima são registados no catálogo (`register_device`, idempotente; o id do MCP fica só em `external_ref`), e passam a publicar `energy.reading_recorded` e `sensor.reading_recorded` reais. A cadeia completa na app: kit → leituras → degraus e identificação (`energy.steps`) → aprendizagem (`energy.learning`).

## O que não se promete

Com **uma só tomada de medição** o sistema separa cargas com potências bem distintas (aquecedor ~2000 W vs secador ~600 W), mas **não** garante a identificação de aparelhos pequenos (< 100 W), de dois aparelhos em simultâneo com potências próximas, nem a distinção de dois aparelhos iguais em quartos diferentes. O resultado tem sempre `confidence` e pode ser `unknown`; o resíduo divide-se por igual. Os próprios autores do PDF dizem que o NILM «funciona para cargas grandes» (§15.1).

## Estado do hardware que condiciona este módulo

| Facto | Estado (ver [mcp-capabilities.md](../integrations/mcp-capabilities.md)) | Consequência |
|---|---|---|
| Unidade de `instantPower` | **Não declarada** (valor, min 0, max 50000, sem unidade) | Sem `MCP_INSTANTPOWER_UNIT`, `power_w = null` e **não há `measured`**. Calibrar com carga conhecida |
| Escrita na lâmpada | Resposta «device updated» mas **efeito físico não comprovado** | Feedback por cor e «desligo?» não podem ser afirmados REAL |
| Escrita na tomada | **Nunca testada** (`multiPower` com `switch_1`) | Corte do aquecedor só com MCP-05 aprovado |
| Latência | ~0,65–0,87 s por leitura; ~0,9 s por ciclo | Degraus a 5 s de resolução; aparelhos ligados ≥ 2 min na demo |

Plano alternativo (PDF §20 #2): se não houver watts, potência nominal × estado ligado/desligado, com `provenance=estimated`.

## Ficheiros existentes reutilizáveis

`connectors/mcp_home.py`, `altice_auth.py`, `altice.py`, `write_grant.py`, `mcp_verify.py`, `fake_home.py`, `contracts/home.py`, `features/mcp/router.py`; Makefile `mcp-*`.

## Ficheiros novos previstos

`features/devices/`, `features/energy/{steps,signatures,locate,router,service,tests}`, `contracts/energy.py`. O simulador de leituras e o replay de um mês ficam em `features/energy/simulation.py` (**PROPOSTA**).

## Integração com o catálogo HOUSE-03 (interface disponível na branch do PR #142)

P1 descobre apenas dispositivos fornecidos pelo conector autorizado para a casa e usa o UUID
interno devolvido pelo catálogo. `Device.external_ref` é uma identidade operacional privada: não
deve vir de um pedido de inquilino nem sair em DTOs, eventos ou logs. O registo MCP é idempotente
por `(household_id, source, external_ref)` e mantém o UUID interno em replays.

```python
catalog.register_device(conn, discovered_device)
signatures = catalog.signatures_for_household(conn, household_id)
meter_history = catalog.meters_for_period(conn, household_id, appliance_id, start, end)
```

`catalog` é injetado com o tipo `ApplianceCatalog` de `contracts.appliance_catalog`; a feature de
energia não importa `features.appliances`. O composition root fornece o adapter SQLite de HOUSE-03.

`catalog.save_appliance_signature(conn, household_id, signature)` grava aprendizagem de P1. As assinaturas
são candidatas para `ApplianceMatch`; a tomada habitual não identifica o que estava ligado. P1
mantém `unknown`/`ambiguous`, guarda candidatos e confiança e não força um vencedor em cargas
simultâneas ou próximas.

`meters_for_period` divide o período nas fronteiras do histórico e devolve `device_id=None` onde não
havia associação. `context_segments_for_consumption` divide propriedade, âmbito e divisão habitual
nas fronteiras de estado; não altera a localização observada em `ConsumptionEvent` e não distribui
energia pelos segmentos. Se o episódio atravessa uma
fronteira e P1 não consegue dividi-lo com leituras observadas, P4 recebe contexto ambíguo e não deve
repartir a energia pelo tempo decorrido.

## Dependências

Precisa de P5 (`core/db`, `core/events`, `households` para `Appliance.owner`). Alimenta P4 e P3.

## Critérios de aceitação

- Com o simulador, três aparelhos de potências distintas ligados em sequência geram os `ConsumptionEvent` esperados (nomes e confiança acima do limiar) em CI, sem hardware.
- Um degrau sem correspondência gera `unknown` e nunca um aparelho inventado.
- Com MCP real: leitura de `instantPower` só vira `measured` depois de a unidade estar confirmada e registada.
- Nenhuma escrita física sem flag + grant + autorização (regra já implementada, mantém-se).

## Testes

Tudo com `FakeHome` e relógio simulado (sem rede nem hardware): degraus, histerese, dois aparelhos simultâneos, termóstato a ciclar, desligar sem leitura. Hardware só pelo [guia de validação](../development/guia-validacao-manual.md) (MCP-03, MCP-05, MCP-06), com registo do resultado lá.
