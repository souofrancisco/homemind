# Arquitetura
Fonte: Docs separadores 25–29 (https://docs.google.com/document/d/1b9Lq2ZejWwpkt-by3U_Belzig1Or-jZxCQE2yLQSoyU/edit?tab=t.0). Aqui só decisões técnicas; não duplicar o Docs.

Browser → API FastAPI → serviços (Stay, Permission, Plan, Turnover, Event) → `DeviceGateway` → Altice MCP.

```
HomeMind API
   ↓
DeviceGateway  (discover, get_states, execute)
   ├── SimulationProvider   (mode=SIMULATION, sempre rotulado)
   └── AlticeMCPProvider    (mode=REAL; único módulo que importa o SDK MCP)
```
- Só o `ActionExecutor`, após aprovação, pede escrita ao gateway. O gateway não decide autorização.
- Monólito modular: spaces, stays, permissions, devices, plans, turnover, events.
- SQLite; BD separada por modo (`homemind-simulation.db` / `homemind-real.db`).
- `ENABLE_PHYSICAL_WRITES=false` por defeito.
- Contratos (entidades/estados) em `backend/app/contracts/` — a fechar nos primeiros 60–90 min de 16/11 (Docs sep. 26).
- Decisões: `docs/decisions/` (um ficheiro por decisão).
