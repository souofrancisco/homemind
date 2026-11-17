# Documentação — Conta Certa

> **Estado:** o produto passou de ObjectOS para **Conta Certa** (reorganização documental de 17/11/2026, reconciliada com o v5.1). O código ainda é o do ObjectOS; os documentos marcados **PLANEADO** descrevem o que vai ser construído, não o que existe. Ver [architecture/migration.md](architecture/migration.md).

Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs (Connected Home).

## Por onde começar

| Sou… | Ler por esta ordem |
|---|---|
| Novo na equipa | [product/vision.md](product/vision.md) → [architecture/overview.md](architecture/overview.md) → [development/team.md](development/team.md) |
| Programador (qualquer módulo) | A minha secção em [development/team.md](development/team.md) → o meu documento em `modules/` → [architecture/contracts.md](architecture/contracts.md) e [architecture/data-model.md](architecture/data-model.md) |
| A preparar a demo | [development/mvp.md](development/mvp.md) → [development/risks.md](development/risks.md) |
| A trabalhar com o MCP | [integrations/altice-mcp.md](integrations/altice-mcp.md) |

## Índice

### Produto (`product/`)

| Documento | Conteúdo |
|---|---|
| [vision.md](product/vision.md) | Problema, os três pilares, princípios, o que a Conta Certa não é |
| [personas.md](product/personas.md) | Senhorio, inquilino, operador: percursos, funcionalidades, limites de acesso |
| [requirements.md](product/requirements.md) | Requisitos com origem (PDF, DECISÃO, PROPOSTA), prioridade e âmbito do MVP |

### Arquitetura (`architecture/`)

| Documento | Conteúdo | Estado |
|---|---|---|
| [overview.md](architecture/overview.md) | Arquitetura implementada vs planeada, módulos, comunicação | PLANEADO |
| [data-model.md](architecture/data-model.md) | Entidades, relações, estados, proveniência | PLANEADO |
| [contracts.md](architecture/contracts.md) | Modelos, eventos e endpoints REST propostos | PLANEADO |
| [event-flow.md](architecture/event-flow.md) | Fluxo de eventos, confirmação de consumo, cálculo da fatura (Mermaid) | PLANEADO |
| [migration.md](architecture/migration.md) | Matriz KEEP / ADAPT / REPLACE / REMOVE e plano de migração | PLANEADO |
| [api-implementada.md](architecture/api-implementada.md) | API REST/WebSocket que **existe hoje** no código (ObjectOS) | IMPLEMENTADO |

### Módulos (`modules/`)

| Documento | Dono | Conteúdo |
|---|---|---|
| [households.md](modules/households.md) | P5 | Casas, quartos, moradores, permissões, persistência |
| [energy.md](modules/energy.md) | P1 | Dispositivos, leituras, degraus, assinaturas |
| [presence.md](modules/presence.md) | P2 | Câmara na porta, presença, estado da casa |
| [billing.md](modules/billing.md) | P4 | Atribuição, fatura, recibos, orçamentos, alertas |
| [notifications.md](modules/notifications.md) | P3 | Centro de notificações, confirmações, preferências |
| [agent.md](modules/agent.md) | P3 | Assistente de IA, ações sugeridas, automações |

### Desenvolvimento (`development/`)

| Documento | Conteúdo |
|---|---|
| [team.md](development/team.md) | Divisão do trabalho pelas cinco pessoas |
| [roadmap.md](development/roadmap.md) | Fases F0–F3, prioridades, bloqueios, ordem de trabalho (espelho da issue #129 e do GitHub Project) |
| [mvp.md](development/mvp.md) | MVP, cenário de demo, real vs simulado, plano B |
| [backlog.md](development/backlog.md) | Mapa épico → issues reais (#58–#132) e destino das issues antigas |
| [risks.md](development/risks.md) | Riscos técnicos e limites do hardware |
| [testing.md](development/testing.md) | Estratégia de testes e critérios de qualidade |
| [guia-validacao-manual.md](development/guia-validacao-manual.md) | Roteiro de validação manual (herdado; ver nota no topo) |

### Integrações (`integrations/`)

| Documento | Conteúdo |
|---|---|
| [altice-mcp.md](integrations/altice-mcp.md) | Ponto de entrada MCP: regras, estado da evidência, medições reais herdadas |
| [mcp-demo.md](integrations/mcp-demo.md) | Operação: OAuth, modo MCP, escritas autorizadas, erros |
| [mcp-capabilities.md](integrations/mcp-capabilities.md) | Capacidades observadas, hipóteses, bloqueios de hardware |
| [mentor-questions.md](integrations/mentor-questions.md) | Perguntas abertas aos mentores Altice |
| [mcp-p3-relatorio.md](integrations/mcp-p3-relatorio.md) | Relatório de passagem do MCP (correções e testes) |

### Decisões e arquivo

| Documento | Conteúdo |
|---|---|
| [decisions.md](decisions.md) | Decisões (incl. Telegram → aplicação), pressupostos e pontos por resolver |
| [references/](references/README.md) | PDFs originais, **documento v5.1** (`.md`, fonte de produto) e guia MCP oficial (intactos, históricos) |
| [archive/objectos/](archive/objectos/README.md) | Documentação do ObjectOS, só para consulta |

## Convenções dos documentos

- Etiquetas de estado: **IMPLEMENTADO** (existe na `main`), **PLANEADO** (decidido, por construir), **PROPOSTA** (ideia nossa, sem decisão), **PDF §x** (vem dos PDFs originais).
- Proveniência dos dados: `measured` (medição real), `estimated`, `inferred`, `simulated`. Ver [architecture/data-model.md](architecture/data-model.md).
- Os PDFs originais em [references/](references/README.md) não se editam. Onde divergem destes documentos, prevalecem estes (ver [decisions.md](decisions.md)).
- Os documentos antigos `docs/contratos.md`, `docs/mcp-capabilities.md`, `docs/mcp-demo.md`, `docs/objectos-plano.md` e `docs/parallel-work.md` são apontadores curtos: o código, o `.env.example` e o CODEOWNERS ainda citam esses caminhos.
