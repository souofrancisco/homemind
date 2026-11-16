# Frontend
Regras gerais em `../../AGENTS.md` (MVP simples, sem testes, UI = Mantine, sem CSS próprio desnecessário).
- Código por feature em `src/features/<feature>/` (componentes, hooks, `api.ts`); `src/shared/` só para o realmente reutilizável; `src/app/` = shell. Chamadas à API só no `api.ts` da feature (proxy `/api`). Tipos: `shared/api/schema.d.ts` (`make contracts`).
- Mostrar sempre o essencial: loading, erro/401/403, vazio e REAL vs SIMULATION (`SourceBadge`); STALE/UNSUPPORTED/VERIFIED/UNVERIFIED onde o fluxo os usa.
- Mobile-first (hóspede), desktop-first (gestor).
