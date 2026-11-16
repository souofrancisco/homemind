# Trabalho paralelo (3–4 agentes)
Regras base em `AGENTS.md` (MVP simples, sem testes, sem co-autoria nos commits).
- **Unidade = feature.** Cada agente: 1 issue/US → 1 branch → 1 worktree → 1 PR pequeno. `make worktree b=feat/US-12-nome` cria `../homemind-US-12-nome` a partir de `origin/main`. Remover no fim: `git worktree remove ../homemind-US-12-nome`.
- **Nomes:** branch `feat/US-xx-nome` · `fix/nome` · `chore/nome`; PR `US-xx: resumo` (ou `chore: …`), corpo com o template.
- **Sem conflitos por desenho:** routers backend descobertos (`core/features.py`), API do frontend por feature, tipos TS gerados (não versionados). Adicionar uma feature = só ficheiros novos.
- **Ficheiros partilhados** (dono no `.github/CODEOWNERS`): `core/`, `contracts/`, `pyproject.toml`/`uv.lock`, `package.json`/lock, `compose.yaml`, `Makefile`, `.github/`, `.env.example`. Regras: PR próprio e pequeno só para isso; dependência nova só se a tarefa a exigir (`uv add …` / `npm i -E …`); em conflito de lockfile regenerar (`uv lock` / `npm install`), nunca editar à mão. Contratos partilhados só mudam com acordo da equipa.
- **Migrations/BD:** SQLite por modo; esquema de uma feature vive na feature; mudanças a tabelas de outra feature = pedir à dona.
- **Contrato front↔back:** o OpenAPI do FastAPI é a fonte. Mudar um schema/rota → `make contracts && make check`; o `tsc` do frontend falha se o contrato quebrar o código existente.
- **Integrar cedo:** PR pequeno (≤ ~300 linhas), rebase em `main` antes de abrir, merge assim que o CI estiver verde.
- **Antes de concluir:** `make check` (e `make smoke` se tocou Docker/proxy).

## GitHub (manual, Settings; requer o dono)
- Branch protection em `main`: PR obrigatório, checks `check` e `smoke`, 1 aprovação/code owner, sem force-push.
- Auto-merge: ativar "Allow auto-merge"; depois `gh pr merge <n> --auto --squash`.
- Se só um job falhar: `gh run rerun <run-id> --job <job-id>`.
- Issues: labels P0/P1, área (backend/frontend/hardware/security/documentation/devops), `blocked`/`blocked-mcp`. Segredos nunca em código/CI/Docs; `make secrets` verifica.
- Bloqueado >30 min: pedir ajuda com erro reproduzível; SIMULATION rotulado, nunca fingir hardware real.
