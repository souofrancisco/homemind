# Backend
Regras gerais em `../../AGENTS.md` (MVP simples, sem testes, reutilizar a stack).
- Features em `src/homemind/features/<modulo>/` (router, schemas, serviços) consomem contratos Pydantic de `contracts/`; sem imports cruzados entre features exceto via serviços.
- `connectors/`: `DeviceGateway` (discover/get_states/execute) com `SimulationProvider` e `AlticeMCPProvider`. O gateway não decide autorização.
- Config só via `core/config.py`; nunca logar `mcp_auth_token`.
