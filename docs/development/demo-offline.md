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
Não implementa motor financeiro, classificador, notificações ou autenticação.

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
  simulados. Bruno é dono do aquecedor, Carla declara ter usado o aquecedor
  na sala. A entrada/saída pela porta permanece anónima.
- Um medidor da extensão na bancada da sala: perfil determinístico em W,
  chaleira (3 minutos), aquecedor (120 minutos), carga desconhecida e
  uma assinatura ambígua. As probabilidades são **valores de referência
  roteirizados**, não probabilidades calculadas por ENERGY-03.
- Leituras tipadas em W incluem **0 W válido** e ausência (`power_w=None`),
  que são estados distintos; consumos em curso ficam com `energy_wh=None`,
  não com zero. Degraus e consumos ON/OFF têm rótulos/confianças roteirizados,
  não calculados por ENERGY-02/03.
- O pedido `billing.confirmation_needed` é uma entrada válida para o
  consumidor real P3. `demo-replay` apenas persiste a entrada; não arranca o
  lifespan/consumidor FastAPI. A integração isolada testa o handler P3 real,
  a persistência SQLite da notificação e votos humanos distintos através de
  `NotificationService`/D-32. Os eventos `notification.created`,
  `notification.responded` e `billing.attribution_changed` não são fabricados
  pelo cenário. P4 ainda não consome os votos no pipeline real.
- O limiar de orçamento 80% é um evento de referência ilustrativo; o produtor
  de orçamento/alertas não está ligado. A demo também não chama `allocate`.
- Fatura de **120,00 €**: dois exemplos *distintos* da v5.1,
  persistidos na tabela `demo_reference` como
  `reference_bill`/`reference_allocation` (e não nos quadros de
  produção, que ainda pertencem a BILL-02 e sucessores).

| Morador | Fixture A | Fixture B |
|---|---:|---:|
| Ana | 45,12 € | 46,80 € |
| Bruno | 29,76 € | 27,60 € |
| Carla | 24,64 € | 24,40 € |
| Diogo | 20,48 € | 21,20 € |
| **Total** | **120,00 €** | **120,00 €** |

Os recibos são estruturas `BillAllocation` com breakdown validado pelos
contratos F0; **não** foram calculados por `demo-replay`/BILL-02. BILL-02/04
tem testes próprios que executam `allocate` e reproduzem A/B; D-34 fixa
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
Os casos `missing`, `unknown` e `ambiguous` são reproduzíveis;
não são convertidos em medição zero, identidade ou cobrança pessoal.
Repetir o replay não duplica eventos; depois de reiniciar o processo,
`verify` lê a mesma sequência. Falhas de consumidores reais são
geridas pelo barramento F0, não por stand-ins ocultos da DEMO-01.

## Híbrido (PLANEADO, bloqueado por segurança)

`--mode hybrid` **recusa-se explicitamente** enquanto não existir adaptador
aprovado que valide origem, unidade, timestamps, permissão e casa. Quando
MCP-02/ENERGY-03/PRES/APP/BILL estiverem implementados, podem substituir
os produtores/consumidores simulados através dos mesmos contratos.
Dados reais terão `origin=real`, sem ocultar os restantes simulados.
**Nenhuma escrita MCP** está autorizada ou é necessária.

## Checklist do ensaio

1. Correr `make demo-prepare`, `make demo-verify`, `make demo-replay` e
   `make demo-verify`; comparar
   `event_digest`, sequências e recibos.
2. Explicar uma passagem anónima, um match ilustrativo e um desconhecido
   sem atribuição; comparar 0 W com leitura ausente.
3. Para mostrar notificações, executar o evento de confirmação no backend
   P3 real com base isolada: pedido → notificação persistida → votos D-32.
   O CLI de demo offline não cria nem responde a notificações.
4. Mostrar o aviso de 80% como referência e as repartições A/B de 120 €
   **separadamente**; dizer que A/B são fixtures do documento.
5. Se os serviços finais estiverem ligados, validar a UI com APP-02/BILL-02
   sem substituir as fixtures por resultados inventados.
6. Se algo falhar, usar estes comandos offline e identificar a origem
   **SIMULADO** durante o pitch.

Testes: `make test` cobre determinismo, idempotência, reset, isolamento,
presença anónima, falha de leitura, reinício e faturas A/B.
