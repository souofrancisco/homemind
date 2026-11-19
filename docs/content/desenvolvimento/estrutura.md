# Estrutura do repositório

Monorepo com tudo da aplicação em `app/`.

| Caminho | Conteúdo |
|---|---|
| `app/backend/` | FastAPI: `src/homemind/{core,contracts,connectors,features,demo}` |
| `app/frontend/` | React 19 + Vite + Mantine: `src/{app,pages,components,hooks,services,types}` |
| `app/infra/` | Blueprint do Authentik, `local.sh`, alvos `make` auxiliares |
| `docs/` | Documentação do projeto |
| `docs/content/` | **Páginas publicadas** neste website (conteúdo público) |
| `docs/evidence/` | Evidência das validações no browser |
| `.github/workflows/` | `pr-docs.yml` e `publish-docs.yml` (documentação, ativos); `ci.yml` (CI geral, desativado) |
| `CLAUDE.md`, `AGENTS.md` | Regras para agentes de IA e pessoas |
| `Makefile` | Interface de comandos |

Cada feature do backend (`features/<nome>/`) tem router, serviços e testes próprios, e não importa outras features.

*Fonte canónica: `docs/architecture.md`.*
