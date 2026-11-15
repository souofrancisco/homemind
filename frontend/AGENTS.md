# Frontend
- Pessoa 3 dona de `components/`, `api/`, layout; `features/guest` é do portal.
- Estados obrigatórios: loading, vazio, 401/403, MCP offline, STALE, UNSUPPORTED, SIMULATION, VERIFIED/UNVERIFIED. `SourceBadge` distingue REAL/SIMULATION sempre.
- Mobile-first (hóspede), desktop-first (gestor); navegável por teclado. Chamadas só via `src/api/` (proxy `/api`).
