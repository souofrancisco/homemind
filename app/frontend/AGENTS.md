# Frontend
- Código por feature em `src/features/<feature>/` (componentes, hooks, `api.ts`); `src/shared/` só para o realmente reutilizável; `src/app/` = shell. Tipos da API: `shared/api/schema.d.ts` (`make contracts`).  Sem router/registo central ainda: se for adicionado, descobrir rotas com `import.meta.glob('../features/*/routes.tsx', { eager: true })`.
- Estados obrigatórios: loading, vazio, 401/403, MCP offline, STALE, UNSUPPORTED, SIMULATION, VERIFIED/UNVERIFIED. `SourceBadge` distingue REAL/SIMULATION sempre.
- Mobile-first (hóspede), desktop-first (gestor); navegável por teclado. Chamadas à API só no `api.ts` da feature (proxy `/api`).
