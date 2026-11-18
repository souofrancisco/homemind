# AGENTS.md — Conta Certa

Guia único para todos os agentes: **[CLAUDE.md](CLAUDE.md)**. Por área: [app/backend/AGENTS.md](app/backend/AGENTS.md) e [app/frontend/AGENTS.md](app/frontend/AGENTS.md). Documentação: [docs/README.md](docs/README.md).

O produto é a **Conta Certa** (casas partilhadas: cada um paga o que usa). A `main` tem o vertical Conta Certa ligado ao runtime (+ código ObjectOS legado até à BASE-04); o que está «planeado» nos documentos não existe. Distinguir sempre IMPLEMENTADO de PLANEADO.

Resumo das regras que nunca se quebram:

- PR por tarefa a partir de um worktree próprio; sem push direto para `main`.
- `make check` verde antes de pedir revisão.
- Contratos primeiro: não implementar um módulo antes de os contratos dele estarem acordados; mudanças em `contracts/` e em [docs/architecture/contracts.md](docs/architecture/contracts.md) vão juntas.
- Uma feature não importa outra: comunica por contratos e eventos.
- Vídeo só local, sem frames gravados, sem reconhecimento facial; o senhorio nunca vê presença nem imagens; segredos fora do Git e dos logs.
- MCP limitado a `get_home_devices`, `get_device_details`, `update_device_capabilities`, lâmpada e tomada; nenhuma escrita física sem autorização explícita; escrita incerta nunca repetida.
- A aplicação é o único canal de interação (sem Telegram nem bots).
- Nunca apresentar simulação como real nem inventar resultados; proveniência `measured | estimated | inferred | simulated`.
