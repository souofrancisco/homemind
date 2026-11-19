# Migração do ObjectOS para a Conta Certa

> **Estado:** BASE-04 (#74) removeu do backend o motor ObjectOS, as rotas de estado/regras e a cadeia antiga de gestos e deteções. O runtime do `Home` e os coletores MCP foram movidos para `features/energy/home_runtime.py`. A matriz abaixo regista o que foi removido e o legado deliberadamente mantido; não é uma lista de trabalho por executar. O frontend é tratado separadamente.

Estado documentado após a conclusão da BASE-04 (#74). A matriz abaixo é o registo histórico das decisões e do destino dos componentes durante a migração; os componentes listados como removidos não existem no código atual.

## Categorias

| Categoria | Significado |
|---|---|
| **KEEP** | Reutilizável sem grandes alterações |
| **ADAPT** | Reutilizável com alterações (indicadas) |
| **REPLACE** | A implementação será substituída; o conceito mantém-se |
| **REMOVE** | Já removido do backend nesta fase BASE-04 |
| **DEFER** | Mantém-se como está e só se decide depois (ver tabela abaixo) |

## Matriz de migração

Caminhos relativos a `app/backend/src/homemind/` (backend) e `app/frontend/src/` (frontend), salvo indicação. «Resp.» é a futura responsabilidade (ver [development/team.md](../development/team.md)).

### Resumo por área e DEFER

| Área | Destino global | DEFER / nota |
|---|---|---|
| MCP e OAuth (`connectors/*`, `features/mcp`) | KEEP / ADAPT (P1) | Escrita física e unidade de `instantPower`: DEFER até MCP-01 e MCP-04 |
| FakeHome | ADAPT (perfis de aparelhos, MCP-05) | — |
| Vídeo e YOLO | KEEP / ADAPT (só presença na soleira) | Thread, anotação e deteção de objetos/pose removidas; permanecem `dispositivo.py` e `pesos.py` usados pela presença |
| Gestos antigos | REMOVE | `ponte.py` KEEP explícito; sem consumidor de produção |
| Engine de modos e regras JSON | REMOVE | O assistente usa `features/agent/llm.py`; não depende do cliente do motor |
| Eventos e WebSocket | Motor removido | O futuro WebSocket de notificações está PLANEADO e sem rota definida |
| Authentik | KEEP | Papéis na base de dados (P-02) |
| Frontend | KEEP / ADAPT | Nome visível do Android já é «Conta Certa»; os identificadores `pt.homemind.app`: **DEFER** (P-14) |
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
| `features/video/router.py` (`GET /api/video` MJPEG) | **ADAPT** | MJPEG desligado por omissão (PRIV-02: `404` salvo clip allowlisted em demo/fake com flag) e, quando ligado, só para o `operator` (**IMPLEMENTADO**, fix/video-mjpeg-operador); máscara da soleira **PLANEADO** | P2 |
| `features/visao/router.py`, `thread.py`, `detetor.py`, `conversao.py`, `anotar.py` | **REMOVIDO** (BASE-04) | A presença usa o pipeline de `features/presence`, sem pose nem deteção de objetos | P2 |
| `features/visao/dispositivo.py`, `pesos.py` | **KEEP** | `presence/yolo.py` escolhe o dispositivo e usa o peso YOLO de pessoas | P2 |
| `features/gestos/gesto.py`, `parametros.py`, `presenca.py`, `processador.py` | **REMOVIDO** (BASE-04) | Gesto «objeto levantado» e presença binária antiga sem consumidores | P2 |
| `features/gestos/ponte.py` | **REMOVIDO** (BASE-04, limpeza final) | O KEEP previsto no plano não foi mantido na remoção final do módulo | P2 |
| `contracts/eventos.py`, `contracts/visao.py` | **REMOVIDO** (BASE-04, limpeza final) | Os tipos deixaram de ter consumidores após a remoção da ponte | P2 + P5 |
| `contracts/simulacao.py` | **REMOVIDO** (BASE-04) | Geradores só eram usados nos testes dos gestos ObjectOS | P1 + P2 |

### Backend — motor de regras e eventos

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| `features/engine/` (código e testes) | **REMOVIDO** (BASE-04) | Nenhuma feature ativa importa o motor; as rotas antigas já não são registadas | P5 |
| `core/config.py` | **ADAPTADO** (BASE-04) | Campos exclusivos de gestos e YOLO de objetos/pose removidos; config de presença, vídeo e assistente mantida | P5 |
| `contracts/regras.py` | **REMOVIDO** (BASE-04, limpeza final) | O contrato deixou de ser necessário após a remoção dos tipos antigos do frontend | P3 |

### Frontend

| Caminho | Destino | Justificação | Resp. |
|---|---|---|---|
| React 19 + Vite + TypeScript + Mantine, `tsconfig`, ESLint | **KEEP** | Stack pedida | P5 |
| Capacitor / `android/` / `capacitor.config.ts` | **KEEP** | App móvel; o nome visível é «Conta Certa» e o `applicationId`/esquema de URL `pt.homemind.app` ficam até depois da demo (P-14). Push (`@capacitor/push-notifications`) é futuro (**PROPOSTA**) | P5 |
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
| `mocks/home.ts` (`VITE_OBJECTOS_SOURCE=mock`) | **REMOVIDO** (BASE-04 #74) | Já ninguém o usava: o stack ObjectOS do frontend estava inalcançável; a variável saiu também do Compose | P5 |
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
| **M4 — Remoção do ObjectOS (backend)** | **EXECUTADO nesta worktree:** motor, rotas, gestos/deteções e ponte removidos | BASE-04 (#74) |

As rotas antigas não fazem parte do OpenAPI atual. `compose*.yaml`, Makefile e `.github/` ficaram fora das alterações BASE-04; referências residuais são reportadas no PR.

## Documentação antiga

| Antes | Agora |
|---|---|
| `docs/architecture.md` | [archive/objectos/architecture.md](../archive/objectos/architecture.md); substituído por [overview.md](overview.md) |
| `docs/contratos.md` | [api-implementada.md](api-implementada.md) (API que existe hoje) + [contracts.md](contracts.md) (proposta) |
| `docs/estado-para-amanha.md`, `objectos-plano.md`, `parallel-work.md`, `demo-script.md`, `pitch-outline.md`, `executive-summary-outline.md`, `metrics.md` | [archive/objectos/](../archive/objectos/README.md) |
| `docs/mcp-demo.md`, `mcp-capabilities.md`, `mentor-questions.md`, `pessoa3-relatorio.md` | [integrations/](../integrations/altice-mcp.md) |
| `docs/guia-validacao-manual.md` | [development/guia-validacao-manual.md](../development/guia-validacao-manual.md) |
| `docs/references/altice-mcp-guia-ligacao.pdf` | **KEEP** (histórico): guia oficial do MCP, movido de `docs/` com histórico Git preservado. Resolve P-09 |
