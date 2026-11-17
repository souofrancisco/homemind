# Frontend ObjectOS

Regras gerais em [`../../CLAUDE.md`](../../CLAUDE.md). Aqui só o específico do frontend (`src/`).

## Estrutura

| Pasta | Regra |
|---|---|
| `app/` | `App`, `routes.tsx` (páginas e navegação), providers (`AuthProvider`, `HomeProvider`) |
| `pages/` | Só compõem componentes e hooks; sem chamadas à API |
| `components/<área>/` | Apresentação (`home`, `camera`, `events`, `automations`, `layout`) |
| `hooks/` | Estado e ações; falam só com `services/` |
| `services/` | `api/client.ts` (HTTP + token), `auth/` (OIDC), `home/` (REST, WebSocket, vídeo) |
| `mocks/` | Fallback de desenvolvimento no browser (`VITE_OBJECTOS_SOURCE=mock`); nunca por omissão |
| `types/home.ts` | Tipos derivados de `shared/api/schema.d.ts` (gerado por `make contracts`, não versionado) |

## Convenções

- **Mantine primeiro:** componentes, tema e notificações do Mantine; sem CSS próprio quando existe um componente. Ícones de `@tabler/icons-react`.
- **API:** todas as chamadas passam por `services/api/client.ts` (`request`), que junta o Bearer e trata o 401. Nunca `fetch` direto nos componentes. Tipos da API nunca redefinidos à mão.
- **Tempo real:** uma única ligação WebSocket, em `HomeProvider`. O token vai na primeira mensagem, nunca no URL. O vídeo MJPEG é lido com `fetch` + Bearer (`services/home/video.ts`), não com `<img src>`.
- **Estados visíveis:** loading, erro, vazio, offline e origem dos dados. Com `backend: "fake"` ou mock, mostrar sempre **SIMULADO**. Só mostrar sucesso quando o backend o confirma (ex.: `OffResult.success`).
- **Segurança:** o frontend nunca fala com o MCP nem envia frames para fora. Tokens só no armazenamento do `oidc-client-ts` (Keystore no Android).
- **Acessibilidade:** legível à distância (projetor), contraste e foco visíveis; layout funciona em telemóvel (Capacitor) e desktop.

## Verificação

`make check` corre `eslint`, gera os tipos e faz `tsc -b && vite build`. Não há testes unitários de frontend: validar à mão pelo `docs/guia-validacao-manual.md` (capítulo Frontend) com `make dev`.
