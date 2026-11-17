# AGENTS.md — ObjectOS

Instruções para Claude Code, Codex e outros agentes: **[CLAUDE.md](CLAUDE.md)** é a referência principal, juntamente com **[docs/objectos-plano.md](docs/objectos-plano.md)** e a issue atribuída. Substitui as orientações antigas sobre HomeMind Spaces (estadias, hóspedes, permissões e turnover).

## Regras essenciais
- MVP ObjectOS: MEARI RTSP → YOLO objetos/pose → gestos/presença → motor de regras → FakeHome/MCP Altice → painel React.
- Cinco donos de módulos: vídeo/visão (1); gestos/presença (2); Home/MCP (3); motor/LLM/testes (4); frontend (5). Coordenar modelos/contratos partilhados antes de editar.
- Preservar o monorepo `app/backend/src/homemind/` + `app/frontend/`; reutilizar FastAPI, Mantine, Authentik e conector MCP existentes, sem reescrever infraestrutura sem necessidade.
- Nunca persistir ou enviar frames para cloud; nenhum reconhecimento facial. MCP limitado à lâmpada e tomada; não tocar em alarme/segurança. Segredos só em ficheiros locais ignorados pelo Git.
- `FakeHome` e clip MEARI são modos de reserva explicitamente identificados; nunca apresentar simulação como ação real.
- `make check` e testes `pytest` para lógica de gestos e estados com dados simulados; testar hardware manualmente. Não depender de equipamento em CI.
- PR por tarefa nos trabalhos de implementação; sem push direto à main por omissão. Não atribuir autoria fictícia nem inventar testes passados.
