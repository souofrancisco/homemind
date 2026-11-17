# Migração do ObjectOS para a Conta Certa

> **Estado:** a preparação (BASE-05 #130, M0) é só documental: o código, as dependências, o Docker, o Makefile e o CI não foram alterados e `make check` continua verde (ver [development/testing.md](../development/testing.md)). A matriz abaixo é o plano que a BASE-04 (#74) executa; os estados descrevem o destino previsto, não migração executada. Nada do ObjectOS se remove fora de um PR da BASE-04.

Fontes analisadas: código em `app/` na `main` (commit `302f0c9`), `README.md`, `CLAUDE.md`, os três `AGENTS.md`, `docs/` anterior (agora em [archive/objectos/](../archive/objectos/README.md) e [integrations/](../integrations/altice-mcp.md)), Makefile, Compose, issues e PRs (só leitura). Não se executou `make check` nesta tarefa.

## Categorias

| Categoria | Significado |
|---|---|
| **KEEP** | Reutilizável sem grandes alterações |
| **ADAPT** | Reutilizável com alterações (indicadas) |
| **REPLACE** | A implementação será substituída; o conceito mantém-se |
| **REMOVE** | Deixa de fazer parte do produto (a remoção real é uma tarefa posterior) |
| **DEFER** | Mantém-se como está e só se decide depois (ver tabela abaixo) |

## Matriz de migração

Caminhos relativos a `app/backend/src/homemind/` (backend) e `app/frontend/src/` (frontend), salvo indicação. «Resp.» é a futura responsabilidade (ver [development/team.md](../development/team.md)).

### Resumo por área e DEFER

| Área | Destino global | DEFER / nota |
|---|---|---|
| MCP e OAuth (`connectors/*`, `features/mcp`) | KEEP / ADAPT (P1) | Escrita física e unidade de `instantPower`: DEFER até MCP-01 e MCP-04 |
| FakeHome | ADAPT (perfis de aparelhos, MCP-05) | — |
| Vídeo e YOLO | KEEP / ADAPT (só «pessoa» + soleira) | `medir_latencia.py` REMOVE |
| Gestos antigos | REMOVE / REPLACE | `ponte.py` KEEP; `presenca.py` ADAPT |
| Engine de modos e regras JSON | REMOVE / REPLACE (SQLite + eventos) | Cliente NVIDIA (`llm.py`) ADAPT para o assistente |
| Eventos e WebSocket | REPLACE / ADAPT | — |
| Authentik | KEEP | Papéis na base de dados (P-02) |
| Frontend | KEEP / ADAPT | Rename «HomeMind» no Android: **DEFER** (P-14) |
| Docker, Makefile, CI | KEEP | `compose.gpu.yaml`, `compose.mcp*.yaml`: **DEFER** (sem alterações previstas) |
| Testes | KEEP / REMOVE (saem com o motor antigo) | Testes novos por módulo |

### Backend — núcleo e API

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| `main.py`, `openapi.py` | **ADAPT** | Mantém a app FastAPI e o OpenAPI→TS; o `lifespan` passa a criar primeiro a base de dados e o barramento | P5 |
| `core/config.py` | **ADAPT** | `Settings` mantém-se; acrescenta caminho da base de dados e flags da demo | P5 |
| `core/errors.py` | **KEEP** | Formato de erro `{error:{code,message}}` já é o padrão desejado | P5 |
| `core/features.py` | **KEEP** | Descoberta de routers e rotas duplicadas apoiam o trabalho paralelo | P5 |
| `core/` (novo: `db.py`, `events.py`, migrações) | novo | SQLite e barramento de eventos | P5 |
| `features/health` | **KEEP** | `/healthz` público; campo `backend: fake\|mcp` | P5 |
| `features/auth` (`current_user`, `User`, `/api/me`) | **ADAPT** | JWT do Authentik mantém-se; acrescenta resolução de `Membership`/papel | P5 |
| `features/mcp/router.py` (`/api/mcp/tools`) | **ADAPT** | Diagnóstico mantém-se; restringir ao papel operador | P1 |

### Backend — conectores, MCP e FakeHome

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| `connectors/altice_auth.py` (OAuth + PKCE, tokens atómicos, correção do pedido duplicado) | **KEEP** | Integração MCP é central; já corrigida e testada (PR #57) | P1 |
| `connectors/altice.py` | **KEEP** | Wrapper de sessão MCP | P1 |
| `connectors/write_grant.py`, `connectors/mcp_verify.py` | **KEEP** | Grant temporário e verificação física continuam obrigatórios | P1 |
| `connectors/mcp_home.py` (643 linhas; sessão única, polling 5 s, whitelist, releitura) | **ADAPT** | Passa a expor leituras de potência como `EnergyReading` com proveniência; papéis de dispositivo; unidade de `instantPower` confirmada. Whitelist e regra «escrita incerta nunca se repete» mantêm-se | P1 |
| `connectors/fake_home.py` | **ADAPT** | Continua o modo SIMULADO; passa a gerar perfis de potência de aparelhos (replay) para o plano B | P1 |
| `contracts/home.py` (`Home`, `EstadoCasa`) | **ADAPT** | Protocolo mantém-se; acréscimo proposto `ler_leituras()` e papel do dispositivo (por acordo) | P1 + P5 |

### Backend — vídeo, visão e gestos

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| `features/video` (`fonte.py`, `service.py`, `router.py`, `medir.py`) | **ADAPT** | No serviço só clips sintéticos allowlisted em `PROFILE=demo` + `HOME_BACKEND=fake`; fontes RTSP recusadas por PRIV-02; ferramentas não devem recolher dados reais | P2 |
| `features/video/router.py` (`GET /api/video` MJPEG) | **REMOVE / 404 em PRIV-02** | Superfície de frames desativada; reabrir exige endpoint de diagnóstico sem frames/imagens e contrato de autorização revisto | P2 |
| `features/visao/detetor.py` (`DetetorYolo`, YOLO11 + pose + ByteTrack) | **ADAPT** | Mantém-se a classe «pessoa» e o tracking; **sai** a deteção de caneca/livro/comando e a pose | P2 |
| `features/visao/thread.py`, `dispositivo.py`, `pesos.py` | **KEEP** | Thread de visão, escolha de dispositivo (MPS/CUDA/CPU), descarga de pesos | P2 |
| `features/visao/anotar.py` | **ADAPT** | Passa a desenhar só a soleira e a máscara a preto | P2 |
| `features/visao/medir_latencia.py` | **REMOVE** | Mede «gesto → luz», métrica do produto antigo | P2 |
| `features/gestos/gesto.py`, `repeticao.py`, `afinador.py`, `parametros.py` | **REMOVE** | Gesto «objeto levantado» deixa de existir | P2 |
| `features/gestos/presenca.py` (debounce de presença binária) | **ADAPT** | Ideia reutilizada (2 frames para entrar, 3 s para sair) na deteção de passagem na porta | P2 |
| `features/gestos/ponte.py` (thread → `asyncio.Queue`) | **KEEP** | A visão continua numa thread e publica eventos no loop | P2 |
| `features/gestos/processador.py` | **REPLACE** | Passa a emitir `DoorCrossed` (linha na soleira) em vez de `ObjetoLevantado` | P2 |
| `contracts/eventos.py` (`ObjetoLevantado`, `Presenca`) | **REPLACE** | Substituído por `DoorCrossed` e eventos de presença ([contracts.md](contracts.md)) | P2 + P5 |
| `contracts/visao.py`, `contracts/video.py`, `contracts/base.py` | **ADAPT** / **KEEP** / **KEEP** | `visao.py` perde `ObjetoDetetado` e `keypoints`; vídeo e base ficam | P2 |
| `contracts/simulacao.py` | **ADAPT** | Gerador de cenários passa de gestos para leituras e passagens simuladas | P1 + P2 |

### Backend — motor de regras e eventos

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| `features/engine/engine.py` (máquina de estados objeto→modo, espera/suspensão, poupança) | **REMOVE** | Lógica do produto antigo; o conceito de «estados da casa» renasce em presença/alertas | P5 (remoção) |
| `features/engine/rules.py`, `rules.json` | **REMOVE** | Regras objeto→ação deixam de existir. `AutomationRule` é novo | P3 |
| `features/engine/llm.py` (cliente NVIDIA via SDK `openai`, 1 retry, prompt com schema) | **ADAPT** | Reaproveitado para o assistente e para regras de automação em português; continua só texto, sem vídeo | P3 |
| `features/engine/eventlog.py` (`events.jsonl`) | **REPLACE** | Substituído por `domain_event` em SQLite | P5 |
| `features/engine/router.py` (REST + WebSocket `/api/ws`) | **REPLACE** / **ADAPT** | Gestor de ligações WS, autenticação na 1.ª mensagem e fila por cliente extraem-se para um módulo comum e reaproveitam-se; as rotas de modos/regras saem | P5 |
| `features/engine/schemas.py`, `config.py`, `tests/` | **REMOVE** | Associados ao motor antigo (testes saem com o motor) | P5 |
| `contracts/regras.py` | **REMOVE** | Modelo `Rule` do produto antigo | P3 |

### Frontend

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| React 19 + Vite + TypeScript + Mantine, `tsconfig`, ESLint | **KEEP** | Stack pedida | P5 |
| Capacitor / `android/` / `capacitor.config.ts` | **KEEP** | App móvel; o nome «HomeMind» do Android continua cosmético. Push (`@capacitor/push-notifications`) é futuro (**PROPOSTA**) | P5 |
| `app/App.tsx`, `routes.tsx`, `components/layout/Shell.tsx` | **ADAPT** | Estrutura de navegação mantém-se; novas páginas por papel | P5 |
| `app/providers/AuthProvider.tsx`, `services/auth/*` (OIDC + PKCE) | **KEEP** | Login Authentik | P5 |
| `app/providers/HomeProvider.tsx`, `hooks/useHome.ts` (WebSocket único) | **ADAPT** | Passa a transportar `notification` e `notification_update` | P5 + P3 |
| `services/api/client.ts` | **KEEP** | Único ponto de HTTP com Bearer e tratamento de 401 | P5 |
| `services/home/api.ts`, `index.ts`, `types/home.ts` | **ADAPT** | Tipos gerados continuam; serviços novos por domínio | P5 |
| `components/events/*`, `hooks/useEvents.ts`, `utils/events.ts` | **ADAPT** | Linha do tempo reutilizada para histórico de notificações e eventos de consumo | P3 + P5 |
| `components/home/*` (`HomeStatusCards`, `HomeDetails`, `PowerOffModal`) | **ADAPT** | Cartões de estado → resumo da casa/consumo; o modal de «Desligar tudo» mantém-se como ação manual (pendente P-07) | P5 |
| `components/camera/*`, `pages/CameraPage.tsx`, `hooks/useCamera.ts`, `useVideoFrame.ts`, `services/home/video.ts` | **ADAPT** | Passa a diagnóstico do operador; `DemoScenarios` → simulador de leituras/passagens | P5 + P2 |
| `components/automations/*`, `pages/Automations*`, `NewAutomationPage`, `hooks/useRules.ts`, `useNewRule.ts` | **ADAPT** | Fluxo «texto → proposta → confirmar» reaproveitado para `AutomationRule` | P3 + P5 |
| `pages/Suggestion*`, `hooks/useSuggestions.ts`, `mocks/suggestions.ts`, `utils/memoryMarkdown.ts` | **REMOVE** | Sugestões de rotinas/Memory (#30, #31, #51) fora de âmbito | P5 |
| `pages/HomePage.tsx`, `ProfilePage.tsx` | **ADAPT** | Início por papel; perfil passa a incluir preferências de notificação | P5 |
| `mocks/home.ts` (`VITE_OBJECTOS_SOURCE=mock`) | **ADAPT** | Mantém-se como fallback de desenvolvimento, sempre rotulado SIMULADO; dados novos de consumo | P5 |
| Novas páginas (Consumo, Notificações, Faturas e recibos, Orçamento, Casa, Assistente) | novo | Ver [team.md](../development/team.md) | P5 / P3 / P4 |

### Autenticação, infraestrutura e ferramentas

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| `app/infra/authentik/homemind.yaml` (blueprint OIDC), serviços Authentik/Postgres no Compose | **KEEP** | Login e utilizadores. Papéis: decisão P-02 (Authentik vs base de dados) | P5 |
| `app/compose.yaml`, `compose.mcp*.yaml`, `compose.gpu.yaml` | **KEEP** | Sem alterações previstas; o ficheiro SQLite vive no volume de dados do backend | P5 |
| `Makefile` (`check`, `smoke`, `mcp-*`, `worktree`) | **KEEP** | Interface única de comandos | P5 |
| `.github/workflows/ci.yml`, `pull_request_template.md`, `CODEOWNERS` | **KEEP** | CODEOWNERS e template precisam de atualização textual futura (ver abaixo) | P5 |
| Testes (`**/tests/`, `backend/tests/`) | **KEEP** / **REMOVE** | Os de `connectors`, `video`, `health`, `core` ficam; os de `engine` e `gestos` saem com os módulos | cada dono |

## O que nos ficheiros fora da pasta `docs/` ainda cita o ObjectOS

Não foi alterado (fora do âmbito desta tarefa): comentários de código e `app/.env.example` apontam para `docs/contratos.md`, `docs/mcp-capabilities.md`, `docs/mcp-demo.md` e `docs/objectos-plano.md`; `.github/CODEOWNERS` aponta para `docs/parallel-work.md`. Por isso existem apontadores curtos nesses caminhos antigos. **Quando o código e o CODEOWNERS forem atualizados, apagar os apontadores.**

## Plano de migração por fases

| Fase | O que acontece | Pré-requisito |
|---|---|---|
| **M0 — Documentação** (esta tarefa) | Documentos, CLAUDE.md, AGENTS.md | — |
| **M1 — Contratos e base** | Modelos Pydantic dos contratos aceites; `core/db.py` e `core/events.py` | Contratos acordados pelos 5 |
| **M2 — Módulos em paralelo** | `households`, `energy`, `billing`, `notifications`, `presence` em paralelo com o motor antigo ainda a correr | M1 |
| **M3 — Interface** | Novas páginas e navegação por papel; WebSocket com notificações | M2 parcial |
| **M4 — Remoção do ObjectOS** | Apagar `engine`, `gestos` (parte), regras e páginas de sugestões; limpar CODEOWNERS e apontadores | M3 estável e demo ensaiada |

Regra: **enquanto o ObjectOS correr, `make check` tem de continuar verde**; as remoções são PRs próprios, um por módulo, com o dono do módulo a rever.

## Documentação antiga

| Antes | Agora |
|---|---|
| `docs/architecture.md` | [archive/objectos/architecture.md](../archive/objectos/architecture.md); substituído por [overview.md](overview.md) |
| `docs/contratos.md` | [api-implementada.md](api-implementada.md) (API que existe hoje) + [contracts.md](contracts.md) (proposta) |
| `docs/estado-para-amanha.md`, `objectos-plano.md`, `parallel-work.md`, `demo-script.md`, `pitch-outline.md`, `executive-summary-outline.md`, `metrics.md` | [archive/objectos/](../archive/objectos/README.md) |
| `docs/mcp-demo.md`, `mcp-capabilities.md`, `mentor-questions.md`, `pessoa3-relatorio.md` | [integrations/](../integrations/altice-mcp.md) |
| `docs/guia-validacao-manual.md` | [development/guia-validacao-manual.md](../development/guia-validacao-manual.md) |
| `docs/references/altice-mcp-guia-ligacao.pdf` | **KEEP** (histórico): guia oficial do MCP, movido de `docs/` com histórico Git preservado. Resolve P-09 |
