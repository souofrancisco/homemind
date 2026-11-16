# Backend
- Features em `src/homemind/features/<modulo>/` (router, schemas, serviços, `tests/` juntos) consomem contratos Pydantic de `contracts/`; sem imports cruzados entre features exceto via serviços.
- `connectors/`: `DeviceGateway` (discover/get_states/execute) com `SimulationProvider` e `AlticeMCPProvider`. O gateway não decide autorização.
- Testes: `make test`; pytest + TestClient; cobrir 401/403 e revogação. Nenhum teste exige MCP real.
- Config só via `core/config.py`; nunca logar `mcp_auth_token`.
