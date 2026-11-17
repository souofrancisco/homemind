# Frontend
Regras gerais em `../../AGENTS.md` (MVP simples, sem testes, UI = Mantine, sem CSS próprio desnecessário).
- Estrutura em `src/`: `app/` (App, rotas, providers), `pages/` (só compõem componentes e hooks), `components/<área>/` + `ui`, `hooks/` (estado e ações; falam só com `services/`), `services/{api,auth,home}` (HTTP/WebSocket; real vs mock em `services/home/index.ts`), `mocks/` (dados de demonstração), `types/`, `utils/`. Chamadas à API só em `services/`. Tipos da API: `shared/api/schema.d.ts` (`make contracts`).
- Mostrar sempre o essencial: loading, erro/401/403, vazio e REAL vs SIMULATION (`SourceBadge`); STALE/UNSUPPORTED/VERIFIED/UNVERIFIED onde o fluxo os usa.
- Mobile-first (hóspede), desktop-first (gestor).
