# Conta Certa — guia operacional para agentes

Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs (Connected Home). Evolução do ObjectOS para **Conta Certa**: a casa partilhada onde cada um paga o que usa. Regras comuns a todos os agentes; detalhes por área em `app/backend/AGENTS.md` e `app/frontend/AGENTS.md`.

Fonte de verdade do produto: documento Conta Certa v5.1 ([`docs/references/Conta_Certa_Documento_Completo_v5.1.md`](docs/references/Conta_Certa_Documento_Completo_v5.1.md); secções citadas abaixo como §n) e as issues `[CC · …]` do GitHub. Roadmap e dependências: issue #129 e [`docs/development/roadmap.md`](docs/development/roadmap.md). Hierarquia: decisões da equipa ([`docs/decisions.md`](docs/decisions.md)) > v5.1 > evidência técnica verificada > documentação na `main` > código ObjectOS. Se o documento e uma issue discordarem, **a issue ganha**; em dúvida, perguntar.

## Estado do repositório (ler primeiro)

- O **código na `main` é ainda o do ObjectOS**; o que está «planeado» nos documentos **não existe**. Ao escrever código, docs, PRs ou respostas, distinguir sempre **IMPLEMENTADO** de **PLANEADO**.
- Antes de tocar no código antigo, ler [`docs/architecture/migration.md`](docs/architecture/migration.md) (KEEP/ADAPT/REPLACE/REMOVE/DEFER). **Não remover código ObjectOS** fora de um PR da BASE-04 (#74).
- Índice da documentação: [`docs/README.md`](docs/README.md). Divisão por pessoa e ficheiros preferenciais: [`docs/development/team.md`](docs/development/team.md). GitHub Project «Conta Certa — Desenvolvimento»: **PENDENTE** (ainda não criado; ver `docs/decisions.md` D-22).

## Produto

O senhorio instala o serviço; o inquilino sabe as regras desde o anúncio. Três regras (§6.2):

1. **O teu quarto é teu**: tudo o que passa pela tomada do quarto é do morador (ligação pessoa–quarto vem do contrato).
2. **As zonas comuns são de todos**: conta da sala, por igual (A), com pergunta “de quem é esta conta?” (B, recomendada) ou por presença (C). Conta o sítio do aparelho, não o dono.
3. **O sistema avisa do que não bate certo**: orçamento 50/80/100 %, picos em zonas comuns, aparelho pessoal fora do quarto.

O pior caso nunca é pior do que a divisão igual de hoje. Quatro pilares: **Justa** (repartição), **Atenta** (orçamentos e picos), **Segura** (fase 2), **Inteligente** (assistente IA via MCP).

### Dentro do MVP / fora

| Dentro | Fora (não implementar sem pedido explícito na issue) |
|---|---|
| Energia por tomada, degraus e assinaturas (NILM), localização quarto vs zona comum | **Telegram**: não há bot nem grupo; notificações e assistente **dentro da app** |
| Repartição quarto/comum/resíduo, plafond solidário, recibos explicados | HAN/E-REDES e total da casa em tempo real (removido na v5.1) |
| Câmara só na porta (entrou/saiu), presença em casa/fora/incerto, Wi-Fi opt-in | Casa vazia/AWAY e aparelho esquecido ao sair (fase 2) |
| Orçamento, previsão, picos, lâmpada RGB como feedback | Reconhecimento facial, gravação de vídeo, câmaras fora da porta |
| Assistente na app com ferramentas tipadas; “É minha / É de todos” | Integração MEO Energia, multi-imóvel, piloto (F3) |

## Arquitetura

Monorepo em `app/`, stack herdada do ObjectOS e que **prevalece sobre o §16–17 do documento** (que sugere Streamlit e Telegram): Python 3.12 + FastAPI + Pydantic v2 + asyncio; React 19 + Vite + TS + Mantine; Docker Compose; Authentik (OIDC). Um processo FastAPI; visão numa thread; eventos por `asyncio.Queue`.

```text
câmara/clip → features/video → features/visao (thread, YOLO) → fila → presença/contagem
MCP Altice / FakeHome → collector (energia) → eventos persistentes (SQLite, auditoria)
  → energia (degraus, assinaturas, localização) → repartição/recibos → alertas
  → REST/WS → app/frontend (notificações + assistente)
```

| Onde | O quê |
|---|---|
| `app/backend/src/homemind/core/` | `config.py` (Settings), `errors.py`, `features.py` (descoberta de routers) |
| `…/contracts/` | Modelos partilhados |
| `…/connectors/` | `fake_home`, `mcp_home`, `altice_auth` (OAuth), `write_grant`, `mcp_verify` |
| `…/features/<nome>/` | `router.py`, lógica e `tests/` da feature |
| `app/frontend/src/` | `app`, `pages`, `components`, `hooks`, `services`, `mocks`, `types` |

Os nomes `homemind` (pacote, cliente OIDC, Compose) são herdados; não renomear.

**Migração em curso:** o código ObjectOS (gestos por objeto, modos caneca/livro/comando, regras JSON, `rules.json`/`events.jsonl`) é classificado KEEP/ADAPT/REMOVE na BASE-04 (#74) e a persistência passa a SQLite com auditoria na BASE-02 (#72). Não assumir que um módulo ObjectOS sobrevive: ler a BASE-04 antes de o estender.

## Sistemas e issues

Cada issue tem código único (`APP-03`…), uma issue → um PR. Fases: F0 fundação · F1 vertical energia→notificação→fatura · F2 presença e demo sólida · F3 opcional. Prioridades: P0 essencial · P1 aprofundamento · P2 extensão.

| Código | Sistema | Código | Sistema |
|---|---|---|---|
| BASE | Contratos, eventos, migração | PRES | Visão na porta e presença |
| MCP | Altice MCP, telemetria, FakeHome | AGENT | Assistente IA na app |
| ENERGY | Degraus, assinaturas, localização | SAFE | Sensores e conforto (F2/F3) |
| HOUSE | Casas, quartos, atribuição | PRIV | RBAC, consentimentos, retenção |
| BILL | Faturas, repartição, plafond | DEMO | Dataset, guião, CI, E2E |
| APP | Navegação, notificações, recibos | PILOT | Pós-MVP (F3) |
| ALERT | Orçamento, previsão, picos | | |

Respeitar as dependências declaradas na issue (ex.: `MCP-03` bloqueada por `MCP-02`; `SAFE-01/03` por `MCP-03`).

## Fluxo de trabalho

1. Ler a issue, as suas dependências e, se tocar em contratos, [`docs/architecture/contracts.md`](docs/architecture/contracts.md) (proposto) e [`docs/architecture/api-implementada.md`](docs/architecture/api-implementada.md) (real).
2. Uma issue por branch e worktree: `make worktree b=feat/<n>-<nome>` (cria `../homemind-<n>-<nome>` a partir de `origin/main`). Nunca trabalhar no worktree de outro agente.
3. Implementar só o pedido, no estilo existente. Sem dependências, abstrações ou funcionalidades extra.
4. `make check` (lint + pytest + contrato OpenAPI→TS + build) tem de passar. `make smoke` quando tocar em Docker, arranque ou proxy.
5. PR pequeno para `main`. **Nunca fazer push direto para `main`** sem instrução explícita do utilizador nessa tarefa.

Comandos: só os do `Makefile` (ver `README.md`).

## Contratos partilhados

`contracts/`, os eventos e modelos expostos na API e [`docs/architecture/contracts.md`](docs/architecture/contracts.md) mudam juntos e só com acordo da equipa (BASE-03 define o contrato canónico). Tarefas que lhes tocam não correm em paralelo com outras. O frontend nunca redefine tipos da API: usa os gerados por `make contracts`.

## Regras de domínio (não quebrar)

- **Dinheiro e explicabilidade:** repartição determinística em código; arredondamentos explícitos e fecho reconciliado a 100 % da fatura (BILL-04). Cada recibo distingue **medido / estimado / simulado** e é contestável (BILL-05/06). O senhorio só reparte o custo real da fatura.
- **Lâmpada** não mede: consumo estimado 9 W × tempo × brilho.
- **Plafond solidário:** aquecimento básico por quarto pago em comum; só o excesso é individual.
- **Atribuição por aparelho, não por tomada:** a assinatura é reconhecida em qualquer tomada; sem identificação nem evidência, divide-se por igual ou só por quem estava em casa. Consumos abaixo de ~5 kWh/mês são ignorados; o assistente só pergunta quando vale a pena (~0,50 €).
- **Presença** (em casa / fora / incerto): Wi-Fi conta muito a favor e pouco contra; só se considera “fora” após 20–30 min **e** saída pela porta. Um aparelho a continuar ligado não prova presença; só um aparelho a ligar prova. Contradição → pergunta, não acusação.
- **Alertas:** orçamento a 50/80/100 % com previsão; pico = zona comum > 1,5 kW durante > 30 min.
- **Assistente IA:** nunca inventa números; tudo vem de ferramentas tipadas e as contas são feitas em código. Ações sensíveis pedem confirmação humana.

## Segurança e privacidade (inegociável)

- **Vídeo só local:** nunca gravar, registar ou enviar frames; só a soleira da porta é analisada (resto mascarado); sem reconhecimento facial nem identificação por imagem. Só saem eventos (“entrou”/“saiu”); visitas só como número. A identidade de presença vem do telemóvel registado (opt-in), nunca da imagem.
- **RBAC:** o senhorio vê totais mensais por quarto e alertas; **nunca** presença, horários, curvas horárias ou imagens. O morador vê os seus dados. Testes de isolamento obrigatórios (PRIV-01).
- Segredos (`MCP_API_KEY`, tokens OAuth, chaves de LLM, URL RTSP) só em `app/.env` e `app/.mcp-auth/` (ignorados pelo Git). Nunca em logs, erros, testes, issues ou docs.
- **MCP — leitura:** `get_home_devices`, `get_device_details`; sensores de contacto, clima e fumo só em leitura e só depois da MCP-03 (valor `unknown` quando não suportado). **Escrita:** `update_device_capabilities`, só lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`). Nunca alarme, segurança, cenários ou timers até uma issue (SAFE-02/04, AGENT-04) o autorizar.
- **Escritas físicas:** `ENABLE_PHYSICAL_WRITES=false` por omissão e grant temporário obrigatório (MCP-04). Um agente **não executa escritas físicas** sem autorização explícita do utilizador nessa tarefa. Uma escrita de resultado incerto nunca é repetida; só se relê.
- Nunca inventar resultados, medições, IDs, capacidades ou confirmações físicas. Distinguir sempre **SIMULADO** (FakeHome, clip, mocks, dataset de inverno) de **REAL** em UI, docs e pitch.
- Em dúvida que afete segurança, autenticação, privacidade ou hardware: escolher o comportamento mais restritivo.

## Testes

- Lógica pura com fakes e relógio simulado; nunca depender de hardware, rede, LLM ou MCP real em `pytest`. Hardware ausente → FakeHome e fixtures determinísticas (MCP-05).
- Correção de bug traz um teste que falha sem ela.
- Hardware valida-se à mão por `docs/guia-validacao-manual.md`; o resultado regista-se lá, sem marcar PASS o que não foi executado.

## Documentação

| Preciso de… | Ler |
|---|---|
| Índice, estado e convenções | `docs/README.md` |
| Estado, bloqueios, prioridades | issue #129, `docs/development/roadmap.md`, `docs/development/backlog.md` |
| Visão, personas, requisitos | `docs/product/` |
| Arquitetura, contratos, modelo de dados, fluxo de eventos | `docs/architecture/` |
| Código ObjectOS → destino | `docs/architecture/migration.md` |
| Um módulo | `docs/modules/<nome>.md` |
| Equipa, MVP, riscos, testes | `docs/development/` |
| MCP e hardware real | `docs/integrations/` (`altice-mcp.md`, `mcp-demo.md`, `mcp-capabilities.md`) |
| Decisões e pontos por resolver | `docs/decisions.md` |
| Gestos, presença, YOLO (código atual) | `app/backend/src/homemind/features/gestos/README.md`, `…/visao/README.md` |
| Testes manuais | `docs/development/guia-validacao-manual.md` |
| PDFs e v5.1 originais | `docs/references/` (históricos; não editar) |

Atualizar o documento correspondente no mesmo PR que muda o comportamento; não criar documentos novos para o que cabe num existente. Etiquetar sempre IMPLEMENTADO / PLANEADO / PROPOSTA.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
