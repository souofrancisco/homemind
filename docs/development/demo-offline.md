# DEMO-01 — dataset e replay offline (IMPLEMENTADO)

Referência: issue [#121](https://github.com/souofrancisco/homemind/issues/121), F0
(`contracts/fixtures.py`, `core/events.py`) e documento v5.1.

## Decisão (três soluções analisadas)

| Alternativa | Simplicidade | Repetibilidade | Reset seguro | SQLite/FakeHome | Novos cenários | Falhas |
|---|---|---|---|---|---|---|
| **A — Python + relógio injetável** | alta | alta | com guarda | direta | editar Python | sim |
| B — SQLite com seed + replay | média | alta | com marcador | direta | SQL/fixtures | sim |
| C — YAML/JSON declarativo | média/baixa | alta | exige motor | exige adaptador | apenas YAML | sim |

**Escolha: A com persistência SQLite do F0.** Não há DSL nova nem dependências
adicionais. O cenário define eventos Pydantic, persiste através de
`append_event` (idempotente), e usa `Database/migrate/seed_demo`.
`demo-prepare` aplica migrações aditivas em falta a uma base de demo existente;
`demo-reset` constrói diretamente o schema atual.
Se o cenário guardado for diferente da versão atual, `demo-prepare` recusa sem
acrescentar eventos e pede `make demo-reset` (que volta a validar o marcador e
o conteúdo exclusivo antes de substituir a base).
Não substitui motores de negócio nem autenticação. `demo-replay` apenas grava as
entradas; os consumidores reais são exercitados pelos testes isolados.

## Executar — sem Docker, rede, câmera, LLM ou MCP

A partir da raiz do repositório, após instalar as dependências do backend:

```sh
make demo-prepare   # cria base exclusiva, seed, catálogo e replay
make demo-verify    # valida sequência, IDs, casas e recibos
make demo-replay    # repete sem duplicar (seguro)
make demo-reset     # recria do zero APENAS a base marcada
make demo-verify
```

Requer Python >=3.12, `uv` e dependências locais disponíveis; no dia da
hackathon instalar antes enquanto houver conectividade. **Estes alvos não
sobem a UI**, não configuram Authentik e não ligam o backend real à base
de demo. A interface REST/React depende de APP-01/02 e das integrações
dos donos; não anunciar interface integrada como concluída.

A base é sempre `app/.demo-data/conta-certa-demo.sqlite3`. Não existe
parâmetro de caminho no CLI e `DB_PATH` não é consultado. Para testes,
`DemoStore(tmp_path)` permite um diretório temporário isolado.

**Proteções do reset:** o CLI usa um caminho fixo, sem aceitar argumentos de
caminho; componentes de caminho, base e sidecars com symlink são recusados;
hardlinks inesperados, cabeçalho SQLite inválido, marcador ausente, outra
casa, residente/conta ou membership fora das fixtures também são recusados.
`demo-reset` recusa WAL/SHM: fechar processos antes de resetar. `prepare`,
`replay` e `verify` deixam SQLite recuperar um WAL de replay interrompido,
desde que os sidecars sejam ficheiros independentes; o replay é uma única
transação. Nenhum outro ficheiro ou base da aplicação é removido.

## O cenário oficial

- Casa F0: Ana, Bruno, Carla e Diogo; 4 quartos, sala, senhorio e operador
  simulados. A entrada/saída pela porta permanece anónima.
- Um medidor da extensão na bancada da sala: perfil determinístico em W.
  O replay guarda apenas `EnergyReadingRecorded`; não declara que a chaleira
  ou o aquecedor foram identificados. O consumidor P1 real (`StepTracker` +
  `make_step_consumer`) transforma estas amostras em degraus e sessões, com
  match vazio (`unknown`), localização desconhecida e sem custo estimado.
  ENERGY-02/03 (degraus e classificador) estão integrados e subscritos no runtime; sem assinatura no catálogo o resultado fica `unknown`.
- Leituras tipadas em W incluem **0 W válido** e ausência (`power_w=None`),
  que são estados distintos. A integração de teste executa o consumidor P1
  sobre as leituras e entrega os eventos de consumo ao atribuidor P4 real.
- Passagens `presence.door_crossed` continuam anónimas. A demo não opta
  moradores por presença, não recolhe Wi-Fi/câmara e não faz check-in manual.
  PRES-03/04 só grava estado para memberships com opt-in; uma resposta manual
  só pode responder a uma pergunta pessoal do sistema. O CLI não inicia esse fluxo.
- O CLI não fabrica `billing.confirmation_needed`, `notification.created`,
  `notification.responded` nem `billing.attribution_changed`. Um teste de
  integração isolado cria um evento de consumo válido para BILL-02, valida o
  pedido de confirmação produzido pelo P4, a notificação persistida pelo P3,
  votos distintos D-32 e a atribuição persistida pelo P4. A amostra de custo
  desse teste é uma entrada simulada explícita, não uma saída calculada pelo
  replay ou por ENERGY-02.
- O limiar de orçamento 80% é um evento de referência ilustrativo; o produtor
  de orçamento/alertas não está ligado. A demo também não chama `allocate`.
- Fatura de **120,00 €**: dois exemplos *distintos* da v5.1,
  persistidos na tabela `demo_reference` como
  `reference_bill`/`reference_allocation` (e não nos quadros de
  produção, que ainda pertencem a BILL-02 e sucessores).

HOUSE-02 (#143), HOUSE-03 (#142) e BILL-02/04 estão integrados na `main`.
`demo-prepare` aplica e testa as migrações de catálogo `0101`/`0102`, billing
`0101`/`0102`, presença `0200` e notificações `0300`. O replay não chama
`ApplianceCatalog`, não cria faturas de produção e não arranca os consumidores
no lifespan da aplicação. A compatibilidade dos contratos de consumo,
atribuição e notificação é verificada em SQLite temporário.

| Morador | Fixture A | Fixture B |
|---|---:|---:|
| Ana | 45,12 € | 46,80 € |
| Bruno | 29,76 € | 27,60 € |
| Carla | 24,64 € | 24,40 € |
| Diogo | 20,48 € | 21,20 € |
| **Total** | **120,00 €** | **120,00 €** |

Os recibos são estruturas `BillAllocation` com breakdown validado pelos
contratos F0; **não** foram calculados por `demo-replay` nem pelo teste de
integração P3/P4. BILL-04 tem testes próprios que executam `allocate` e
reproduzem A/B; D-34 fixa
empates por hash da casa/período. O termo fixo,
os consumos individuais e o resíduo pertencem aos exemplos originais da
documentação, não à sequência de poucos minutos do replay.

**Rigor de proveniência:** `origin=simulated` em todas as entradas.
`kind=measured` é medição *no cenário simulado*, não uma leitura física.
A impressão do CLI inclui `SIMULADO / offline`, contagens e fingerprint.
`event_digest` identifica conteúdo/ordem dos eventos; `recorded_at` e
`schema_migration.applied_at` são tempos de gravação e podem mudar entre
resets. Comparar o **estado lógico**, não os bytes SQLite.

## Erro e recuperação

A falta de câmara, MCP, Wi-Fi ou LLM não interfere no replay. Não inicia
recolha de presença nem operação física MCP. As passagens de porta são apenas
`DoorCrossed` anónimos; nenhuma identidade é inferida por imagem.
O caso `missing` e as sessões `unknown` produzidas por ENERGY-02 são
reproduzíveis; a demo não cria `ambiguous` nem identifica aparelho, residente
ou cobrança pessoal.
Repetir o replay não duplica eventos; depois de reiniciar o processo,
`verify` lê a mesma sequência. Falhas de consumidores reais são
geridas pelo barramento F0, não por stand-ins ocultos da DEMO-01.

## Híbrido (PLANEADO, bloqueado por segurança)

`--mode hybrid` **recusa-se explicitamente** enquanto não existir adaptador
aprovado que valide origem, unidade, timestamps, permissão e casa. Uma
integração futura com sensores reais pode substituir as entradas simuladas
através dos mesmos contratos. Não é feita neste cenário.
Dados reais terão `origin=real`, sem ocultar os restantes simulados.
**Nenhuma escrita MCP** está autorizada ou é necessária.

## Checklist do ensaio

1. Correr `make demo-prepare`, `make demo-verify`, `make demo-replay` e
   `make demo-verify`; comparar
   `event_digest`, sequências e recibos.
2. Explicar uma passagem anónima e uma sessão `unknown` produzida por P1;
   comparar 0 W com leitura ausente.
3. Para mostrar notificações, usar o teste de integração P4 → P3 em SQLite
   isolado: evento simulado de consumo → pedido → notificação → votos D-32 →
   atribuição. O CLI offline não cria nem responde a notificações.
4. Mostrar o aviso de 80% como referência e as repartições A/B de 120 €
   **separadamente**; dizer que A/B são fixtures do documento.
5. Se os serviços finais estiverem ligados, validar a UI com APP-02/BILL-02
   sem substituir as fixtures por resultados inventados.
6. Se algo falhar, usar estes comandos offline e identificar a origem
   **SIMULADO** durante o pitch.

Testes: `make test` cobre determinismo, idempotência, reset, isolamento,
presença anónima, falha de leitura, reinício e faturas A/B.

## Demo web com login real (local) — IMPLEMENTADO

> Fluxo recomendado: `make demo-up` / `make demo-reset` (backend e frontend no anfitrião; ver [../development.md](../development.md)). O que se segue descreve a alternativa em Docker.

`make demo-web-up` cria, de forma idempotente e só em local: Authentik próprio (projeto Compose
`homemind-demoweb`, portas 25173/28000/29000) com seis contas (`ana`, `bruno`, `carla`, `diogo`,
`senhorio`, `operador`; palavra-passe `demo-conta-certa`, sem email para não acionar MFA), uma
**cópia** da base de demo em `app/.demo-web/` e o backend/frontend sobre essa cópia.

- O `sub` de cada conta é obtido por um login OIDC verdadeiro (código + PKCE) e gravado na
  cópia por `python -m homemind.demo.web link`. Só esse comando local escolhe identidades; a
  validação de tokens e o frontend não mudam.
- A original (`app/.demo-data`, `make demo-reset`) é só lida e nunca alterada. A cópia tem o
  seu marcador; `clean`/`link` recusam qualquer outro ficheiro.
- Recriar: `make demo-web-reset` (nova cópia, mantém contas) · `make demo-web-clean` (apaga
  containers, volumes do Authentik e a cópia) e depois `make demo-web-up`.
- Os dados continuam **SIMULADOS**; as contas Authentik são só de desenvolvimento.

## Demo web viva — IMPLEMENTADO

`make demo-up`, `make demo-web-up` e `make demo-web-reset` usam uma cópia própria
ancorada no relógio atual; o cenário oficial offline mantém o relógio fixo e o replay
determinístico. `make demo-web-reset` volta a gerar a cópia com o início do cenário
recente, pelo que é o comando recomendado antes de uma apresentação.

A cópia web inclui a tomada da extensão da sala como medidor `room_meter`, os aparelhos
«Aquecedor do Bruno» e «Chaleira comum», e assinaturas **SIMULADAS**. O classificador,
localizador, billing e restantes consumidores são os serviços reais da aplicação.
O cartão «Simulador da demo» em Diagnóstico pode iniciar as duas sessões. Sem clique,
o aquecedor começa automaticamente cerca de 60 segundos depois do arranque e permanece
ligado cerca de 180 segundos (a chaleira, 155 segundos). As leituras da tomada são SIMULADAS,
com base de 40 W e publicação a cada 5 segundos. No fim de cada sessão a tomada emite uma
leitura em falta e volta à base: o motor fecha então o consumo de imediato (recuperação
definitiva) em vez de esperar os 10 minutos da pausa de termóstato, e o pedido «De quem é
esta conta?» aparece cerca de 4 minutos depois do arranque. O limiar da pergunta da casa demo é
2 cêntimos: a sessão do aquecedor atinge-o e a chaleira curta fica abaixo. O cálculo de
custos existente não é alterado.

`DEMO_LIVE` é ativada por omissão em `PROFILE=demo`; definir `DEMO_LIVE=false` desliga-a.
O emissor exige também `HOME_BACKEND=fake` e uma casa `source_kind=demo`. Nunca é iniciado
com MCP nem executa operações físicas. A origem simulada não representa medições reais.
