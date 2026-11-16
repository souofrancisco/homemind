# Contribuir
**Fluxo:** issue → branch `feat/US-xx` (ou `chore/…`) a partir de `main` → PR pequeno → CI verde + 1 revisão → merge (squash). Sem push direto a `main`, sem force-push.
**Local:** `scripts/test.sh` antes de abrir PR (igual ao CI).
**Issues:** labels P0/P1, área (backend/frontend/hardware/security/documentation/devops), `blocked`/`blocked-mcp`. Atribuir só com username real (mapeamento Pessoa 1–5 → GitHub: por preencher).
**Segredos:** nunca em código, `.env` versionado, CI ou Google Docs (editável por link). Credenciais MCP só em `.env` local. Verificação: `scripts/check-secrets.sh`.
**Contratos:** mudar `app/contracts/` ou fixtures só com acordo da equipa.
**Bloqueado >30 min:** pedir ajuda com erro reproduzível; usar SIMULATION rotulado, nunca fingir hardware real.
**Proteção de `main` (manual, Settings → Branches):** exigir PR, 1 aprovação, checks `backend`, `frontend`, `secrets`, `docker`, sem force-push.
