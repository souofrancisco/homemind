# Backend
- Features em `app/features/<modulo>/` consomem contratos Pydantic de `app/contracts/`; sem imports cruzados entre features exceto via serviços.
- `app/connectors/`: `DeviceGateway` (discover/get_states/execute) com `SimulationProvider` e `AlticeMCPProvider`. O gateway não decide autorização.
- Testes: pytest + TestClient; cobrir 401/403 e revogação. Nenhum teste exige MCP real.
- Config só via `app/core/config.py`; nunca logar `mcp_auth_token`.
