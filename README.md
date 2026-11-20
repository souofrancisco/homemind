# Conta Certa

[![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React_19-149ECA?style=flat-square&logo=react&logoColor=white)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vite.dev/)
[![Mantine](https://img.shields.io/badge/Mantine-339AF0?style=flat-square&logo=mantine&logoColor=white)](https://mantine.dev/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)

[![Documentação](https://img.shields.io/badge/Documentação-online-0A66C2?style=flat-square&logo=readthedocs&logoColor=white)](https://souofrancisco.github.io/homemind/)
[![Deploy da documentação](https://github.com/souofrancisco/homemind/actions/workflows/publish-docs.yml/badge.svg?branch=main)](https://github.com/souofrancisco/homemind/actions/workflows/publish-docs.yml)
[![Docs CI](https://img.shields.io/badge/Docs_CI-MkDocs_strict-2088FF?style=flat-square&logo=githubactions&logoColor=white)](https://github.com/souofrancisco/homemind/actions/workflows/pr-docs.yml)
[![CI geral](https://img.shields.io/badge/CI_geral-desativada-lightgrey?style=flat-square&logo=githubactions)](https://github.com/souofrancisco/homemind/blob/main/.github/workflows/ci.yml)
[![CLI](https://img.shields.io/badge/CLI-Makefile-4C8C2B?style=flat-square&logo=gnubash&logoColor=white)](Makefile)

**Aveiro Tech City Hackathon 2026 · Desafio 3 — Altice Labs (Connected Home)**

*Cada um paga o que usa. A casa trata do resto.*

A **Conta Certa** ajuda a gerir a eletricidade em casas partilhadas: analisa consumos por tomada, identifica aparelhos de forma probabilística, pede confirmação quando há dúvidas e reparte a fatura em valores individuais explicáveis. Inclui orçamentos e notificações, sem dar ao senhorio acesso à presença ou aos horários dos moradores.

## Começar

**Requisitos:** Docker (Compose v2), Make, [uv](https://docs.astral.sh/uv/) e Node.js 22+.

```bash
make setup       # Instalar dependências e criar app/.env
make demo-up     # Iniciar a demonstração
```

| Serviço | Endereço local |
|---|---|
| Aplicação | http://localhost:5173 |
| API / Swagger | http://localhost:8000/docs |
| Authentik | http://localhost:9000 |

As portas são configuráveis em `app/.env`. A demo utiliza **dados simulados** (`FakeHome`), com autenticação local e lógica de negócio executada no backend.

**Contas da demo:** `ana`, `bruno`, `carla`, `diogo` (moradores), `senhorio` e `operador`.  
**Palavra-passe local:** `demo-conta-certa`.

## Comandos

| Comando | Função |
|---|---|
| `make help` / `make help-all` | Ver os comandos disponíveis, incluindo Docker e MCP |
| `make demo-up` | Iniciar a demo |
| `make demo-reset` | Repor o cenário simulado |
| `make down` | Parar os serviços |
| `make auth-up` | Iniciar Authentik |
| `make backend` / `make frontend` | Desenvolvimento local com reload (em dois terminais) |
| `make test` / `make lint` | Testes e análise estática |
| `make check` | Validação local: lint, testes, contratos, build e Docker |
| `make contracts` / `make build` | Gerar tipos OpenAPI e compilar o frontend |

Para desenvolvimento, executa `make auth-up` e depois `make backend` e `make frontend` em terminais separados. O CI geral está desativado; `make check` é a verificação local recomendada.

## Arquitetura

**Frontend:** React 19, TypeScript, Vite e Mantine.  
**Backend:** Python 3.12, FastAPI, Pydantic e SQLite, com contratos tipados e eventos de domínio.  
**Autenticação:** Authentik (OIDC). **IoT:** adaptadores `McpHome` (Altice) e `FakeHome` (demo).

A identificação energética é probabilística; quando a evidência não chega, aplicam-se as regras de atribuição da casa. A cadeia completa com hardware real ainda requer validação.

## Documentação

**[Documentação online](https://souofrancisco.github.io/homemind/)** · [Arquitetura](docs/architecture.md) · [Desenvolvimento](docs/development.md) · [Fluxos funcionais](docs/functional-flows.md)

## Contribuidores

| Nome | GitHub | Área |
|---|---|---|
| Bruno Vieira | [@brunoviera88](https://github.com/brunoviera88) | MCP, energia e identificação de aparelhos |
| Miguel Santos | [@1Mii](https://github.com/1Mii) | Visão e presença |
| Francisco Correia | [@souofrancisco](https://github.com/souofrancisco) | Arquitetura, frontend e integração |
| Afonso Santos | [@Amorim3000](https://github.com/Amorim3000) | Faturação, atribuição e alertas |
| Rafael Matos | [@rafaelmat0s-dev](https://github.com/rafaelmat0s-dev) | Notificações e assistente |
