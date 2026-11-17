# Frontend ObjectOS
Ler `../../AGENTS.md`, `CLAUDE.md` da raiz e `docs/objectos-plano.md`. Reutilizar `app/frontend/src/`, React/Vite/TypeScript, Mantine, router, OIDC e contratos OpenAPI existentes; não reiniciar o projeto. Construir painel do ObjectOS: vídeo MJPEG, WS estado, presença, modo, saúde câmara/MCP, registo, poupança, regras com confirmação e botão desligar tudo. Indicador de processamento local e REAL/FakeHome visível. Não aceder diretamente ao MCP nem carregar frames em cloud.

Regras gerais em `../../AGENTS.md` (MVP simples, UI = Mantine, sem CSS próprio desnecessário).
- Estrutura em `src/`: `app/` (App, rotas, providers), `pages/` (só compõem componentes e hooks), `components/<área>/`, `hooks/` (estado e ações; falam só com `services/`), `services/{api,auth,home}` (HTTP/WebSocket; real vs mock em `services/home/index.ts`), `mocks/` (só fallback de desenvolvimento), `types/`, `utils/`. Chamadas à API só em `services/`. Tipos da API: `shared/api/schema.d.ts` (`make contracts`).
- Mostrar sempre o essencial: loading, erro/401/403, vazio e origem real vs simulada.
- Mobile-first (hóspede), desktop-first (gestor).
