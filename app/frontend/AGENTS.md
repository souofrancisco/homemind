# Frontend — Conta Certa

Regras gerais em [`../../CLAUDE.md`](../../CLAUDE.md). Aqui só o específico do frontend (`src/`). A aplicação React/Mantine/Capacitor é a **interface principal** da Conta Certa para moradores e senhorios (centro de notificações, confirmações, recibos, assistente): **planeado**. O código atual é o painel do ObjectOS (Início, Câmara, Eventos, Automações, Perfil); ver [`docs/architecture/migration.md`](../../docs/architecture/migration.md).

## Estrutura (implementada)

| Pasta | Regra |
|---|---|
| `app/` | `App`, `routes.tsx` (páginas e navegação), providers (`AuthProvider`, `HomeProvider`) |
| `pages/` | Só compõem componentes e hooks; sem chamadas à API |
| `components/<área>/` | Apresentação (hoje `home`, `camera`, `events`, `automations`, `layout`) |
| `hooks/` | Estado e ações; falam só com `services/` |
| `services/` | `api/client.ts` (HTTP + token), `auth/` (OIDC), `home/` (REST, WebSocket, vídeo) |
| `mocks/` | Fallback de desenvolvimento no browser (`VITE_OBJECTOS_SOURCE=mock`); nunca por omissão; sempre SIMULADO |
| `types/home.ts` | Tipos derivados de `shared/api/schema.d.ts` (gerado por `make contracts`, não versionado) |

## Convenções

- **Mantine primeiro:** componentes, tema e notificações do Mantine; sem CSS próprio quando existe um componente. Ícones de `@tabler/icons-react`.
- **API:** todas as chamadas passam por `services/api/client.ts` (`request`), que junta o Bearer e trata o 401. Nunca `fetch` direto nos componentes. Tipos da API nunca redefinidos à mão.
- **Tempo real:** uma única ligação WebSocket, em `HomeProvider`. O token vai na primeira mensagem, nunca no URL. O vídeo MJPEG é lido com `fetch` + Bearer (`services/home/video.ts`), não com `<img src>`.
- **Estados visíveis:** loading, erro, vazio, offline e origem dos dados. Mostrar sempre **SIMULADO** com `backend: "fake"`, mock ou dados `simulated`; mostrar a proveniência (medido, estimado, inferido, simulado) de cada valor de energia e de cada recibo. Só mostrar sucesso quando o backend o confirma.
- **Segurança:** o frontend nunca fala com o MCP nem envia frames para fora. Tokens só no armazenamento do `oidc-client-ts` (Keystore no Android).
- **Acessibilidade:** legível à distância (projetor), contraste e foco visíveis; layout funciona em telemóvel (Capacitor) e desktop.

## Regras para as páginas novas (planeado)

- **Ecrãs por papel** (inquilino, senhorio, operador): o servidor decide o que cada papel recebe; a UI só mostra o que vem. O ecrã do senhorio não tem presença, aparelhos individuais nem imagens ([`personas.md`](../../docs/product/personas.md)).
- **Notificações:** centro de notificações com ações interativas («É minha / É de todos / Não sei»); recebem-se por WebSocket (`notification`, `notification_update`) e recuperam-se por `GET /api/notifications` ao reconectar ([`contracts.md`](../../docs/architecture/contracts.md)). Repetir uma resposta devolve `409`: tratar sem erro bruto.
- **Páginas previstas:** Consumo, Notificações, Faturas e recibos, Orçamento, Casa, Assistente. Nova página de topo: uma linha em `routes.tsx`.
- **Assistente:** mostra a proveniência; uma ação sugerida só se executa depois de o utilizador confirmar.
- Os tipos novos vêm sempre do OpenAPI gerado; se o contrato ainda não existir, não os inventar: pedir o contrato (P5).

## Verificação

`make check` corre `eslint`, gera os tipos e faz `tsc -b && vite build`. Não há testes unitários de frontend (avaliação pendente P-12): validar à mão pelo [`guia de validação`](../../docs/development/guia-validacao-manual.md) com `make dev`.
