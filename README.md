# ObjectOS

**Aveiro Tech City Hackathon 2026 · Desafio 3 — Altice Labs (Connected Home)**

Protótipo de casa inteligente controlada por gestos com objetos comuns. A câmara MEARI por RTSP identifica **caneca, livro e comando** usando YOLO e pose. Levantar o objeto ativa um modo (por exemplo, leitura); a presença mantém o ambiente. Ao sair da divisão, o sistema entra em espera e suspende luz e tomada após um período, restaurando-as quando alguém regressa. O botão **Desligar tudo** permite controlo explícito.

**Privacidade:** vídeo processado localmente; nenhum frame armazenado nem enviado para serviços externos. A NVIDIA recebe apenas texto durante a configuração de regras, nunca o stream de vídeo. O MCP Altice só pode atuar em lâmpada e tomada após validação de capabilities.

## Estado atual

Este repositório era o *HomeMind Spaces* e já contém infraestrutura reutilizável: FastAPI feature-first, React/Vite/TS/Mantine, Authentik OIDC, cliente MCP em Python, Docker Compose e CI. **A visão, os gestos, o motor de regras e o painel ObjectOS ainda têm de ser desenvolvidos.** Não confundir infraestrutura existente com funcionalidades demonstradas.

## Documentação e tarefas

- [Plano de implementação ObjectOS](docs/objectos-plano.md) — requisitos, arquitetura, interfaces, cinco responsáveis, critérios e riscos.
- [Guia de validação manual](docs/guia-validacao-manual.md) — tutorial passo a passo para testar as funcionalidades e decidir se a demo está pronta.
- [Instruções para Claude e agentes](CLAUDE.md) — regras, paths reais e segurança.
- [Trabalho paralelo](docs/parallel-work.md) — divisão por pessoa e integração.
- [Issues ObjectOS](https://github.com/souofrancisco/homemind/issues) — unidades de implementação e critérios de aceitação.
- [MCP Altice: login, escritas autorizadas e demo](docs/mcp-demo.md)
- [Capacidades MCP](docs/mcp-capabilities.md) — conferir schemas reais antes de fazer escritas. O que estiver legado/por validar não deve ser dado como confirmado.

## Stack

Backend Python 3.12+, FastAPI, Pydantic v2, asyncio, SDK `mcp` (existentes); OpenCV/FFmpeg, Ultralytics YOLO11s e YOLO11s-pose/ByteTrack, SDK `openai` para NVIDIA (**a adicionar nas issues correspondentes**). Frontend React, Vite, TypeScript, Mantine já existentes. Regras e eventos simples em `rules.json` / `events.jsonl`, sem base de dados nova para o ObjectOS.

## Estrutura real

```text
app/
  backend/
    src/homemind/
      main.py
      core/config.py
      connectors/altice.py
      features/{auth,health,mcp}/
      ... novos módulos ObjectOS a implementar
  frontend/
    src/
  compose.yaml
docs/objectos-plano.md
CLAUDE.md
AGENTS.md
```

O plano original descreve `backend/video.py` e `frontend/` conceptualmente; seguir os paths reais do monorepo para não criar uma aplicação paralela.

## Desenvolvimento

```bash
cp app/.env.example app/.env
make dev       # Docker Compose (backend + frontend + Authentik)
make check     # lint, contratos OpenAPI, build, validação de compose
```

A infraestrutura atual disponibiliza frontend em `http://localhost:5173`, backend em `http://localhost:8000` e Authentik em `http://localhost:9000` com a configuração de desenvolvimento existente. Não pressupor que as rotas ObjectOS já existem.

As variáveis do ObjectOS a definir durante a implementação incluem `VIDEO_SOURCE`, `HOME_BACKEND=fake|mcp`, `PROFILE=normal|demo`, `NVIDIA_API_KEY` e as variáveis MCP existentes (`MCP_ENDPOINT`, `MCP_API_KEY`, `MCP_OAUTH_*`, `ENABLE_PHYSICAL_WRITES`; ver `app/.env.example`). Guardar segredos fora do repositório. O `FakeHome` e o clip MEARI são reservas de desenvolvimento/demo, sempre identificados como simulação.

## Equipa (cinco pessoas)

| Pessoa | Responsabilidade |
|---|---|
| 1 | Vídeo RTSP, YOLO/pose, MJPEG, integração e entregáveis |
| 2 | Gestos, presença, filas de eventos e afinação |
| 3 | `Home`, `FakeHome`, `McpHome`, OAuth e segurança do MCP |
| 4 | Regras, máquina de estados, poupança, LLM, testes |
| 5 | Painel React/Mantine, WebSocket, vídeo, regras e controlo |

As issues indicam o número do responsável; o assignee GitHub será definido quando houver o mapeamento dos cinco usernames.

## Demo e entregáveis

Meta de latência gesto→luz **<4 segundos**, RTSP <1,5 s de atraso, inferência ≥10 FPS com GPU, dez demos consecutivas antes de extras. PDF executivo 2 páginas com prazo **18 de novembro de 2026 às 19h**, PPT no template oficial e apresentações de 3 e 5 minutos. Não afirmar controlo real até haver chamada MCP e estado confirmado.

## Segurança

Nenhum reconhecimento facial, persistência de frames ou transmissão do vídeo para cloud. Não controlar alarmes ou equipamentos de segurança; usar apenas ações autorizadas sobre lâmpada e tomada. Não inventar tools ou resultados MCP. As funcionalidades antigas de estadias não fazem parte do escopo ObjectOS.
