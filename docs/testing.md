# Testes
Local: `make check` (= CI) · `make smoke` (Docker). Testes backend junto de cada feature (`features/<f>/tests/`). CI não usa credenciais MCP.
Obrigatórios (Docs sep. 33): 401 sem sessão; 403 estadia alheia, PRIVATE de outro, pós-check-out; preview = 0 writes; sem aprovação = 0 writes; timeout sem retry; REAL/SIMULATION não se misturam; turnover PENDING bloqueia check-in.
Evidências do júri: criar `docs/demo-evidence.md` (requisito, modo, cenário, resultado, commit, hora, link).
