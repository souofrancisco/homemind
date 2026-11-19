# Conta Certa — guia para agentes

Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs. **Conta Certa**: casa partilhada onde cada um paga o que usa. Entrada: [`README.md`](README.md). Índice: [`docs/README.md`](docs/README.md). Fluxo de IA: [`docs/ai-workflow.md`](docs/ai-workflow.md).

Hierarquia de verdade: decisões da equipa ([`docs/decisions.md`](docs/decisions.md)) > issues `[CC · …]` e Project > [v5.1](docs/references/Conta_Certa_Documento_Completo_v5.1.md) > código e testes > documentação. Issue e documento discordam → **a issue ganha**; em dúvida, perguntar. Distinguir sempre **IMPLEMENTADO** de **PLANEADO**; fluxos comprovados: [`docs/functional-flows.md`](docs/functional-flows.md).

# Parte A — Regras de desenvolvimento

## Stack e estrutura
Python 3.12 + FastAPI + Pydantic v2 + SQLite (barramento de eventos); React 19 + Vite + TS + Mantine; Authentik (OIDC). Monorepo `app/` ([`docs/architecture.md`](docs/architecture.md)). Os nomes `homemind` (pacote, cliente OIDC, Compose) são herdados: não renomear. O código ObjectOS (motor, gestos e páginas antigas) foi removido na BASE-04 (#74); consultar [`docs/architecture/migration.md`](docs/architecture/migration.md) para o registo histórico.

## Arquitetura (não quebrar)
- Uma feature **não importa outra**: comunica por `contracts/` e eventos de domínio. Recursos partilhados (SQLite, barramento) em `core/` (P5).
- **Contratos** (`contracts/`, eventos, modelos da API, [`docs/architecture/contracts.md`](docs/architecture/contracts.md)) mudam juntos e só com acordo da equipa; tarefas que lhes tocam não correm em paralelo. O frontend usa os tipos gerados (`make contracts`), nunca os redefine.
- Autorização no servidor por papel, DTOs distintos; rota nova ⇒ teste papel × rota (PRIV-01). Detalhes: [`app/backend/AGENTS.md`](app/backend/AGENTS.md), [`app/frontend/AGENTS.md`](app/frontend/AGENTS.md).

## Equipa (propriedade por módulo)
P1 `brunovieira88` MCP/energia/aparelhos · P2 `1Mii` visão/presença · P3 `RafaelMat0s-Dev` notificações/assistente · P4 `Amorim3000` faturação/atribuição/alertas · P5 `souofrancisco` arquitetura/frontend/integração/demo. Ficheiros preferenciais: [`docs/development/team.md`](docs/development/team.md). Mudar propriedade ou tocar no módulo de outra pessoa → acordo.

## Ambiente (regra obrigatória)
**Authentik em Docker; backend e frontend no anfitrião, com reload.** `make setup` · `make auth-up` · `make backend` · `make frontend` (ou `make demo-up` para a demo SIMULADA, `make demo-reset`, `make down`). `make help` / `make help-all`; só se usam comandos do `Makefile`. Detalhes e `.env`: [`docs/development.md`](docs/development.md). Docker completo (`make dev`) é alternativa.

## Trabalho
1. Escolher uma issue em *Pronto* no [Project](https://github.com/users/souofrancisco/projects/1), sua, sem *blocked by* abertos. Uma issue → um branch → um worktree → um PR.
2. `make worktree b=feat/<n>-<nome>` (a partir de `origin/main`); copiar `app/.env`. Nunca trabalhar no worktree de outro agente.
3. Implementar só o pedido, no estilo existente; sem dependências, abstrações ou funcionalidades extra. Atualizar o documento correspondente no mesmo PR.
4. Testar: `make check` (lint + pytest + OpenAPI→TS + build); `make demo-up` + browser para UI. Lógica pura com fakes e relógio simulado; nunca hardware, rede, LLM ou MCP real em `pytest`. Bug corrigido traz teste que falha sem a correção. Hardware valida-se à mão ([guia](docs/development/guia-validacao-manual.md)); nunca marcar PASS o que não foi executado.
5. PR pequeno para `main` com: o que mudou, testes realmente corridos, limitações. **Nunca push direto para `main`**, nem merge por agentes. Sem CI ativa: não a reativar nem alterar o workflow `CI` (`ci.yml`). Exceção: os workflows de documentação `pr-docs.yml` e `publish-docs.yml` estão ativos (website em `docs/`, ver [`docs/README.md`](docs/README.md)).
6. Codex: delegar só trabalho independente e sem ficheiros em comum ([`docs/ai-workflow.md`](docs/ai-workflow.md)); rever sempre o *diff*; no máximo duas rondas.
7. Não repetir `graphify`: orientar uma vez com `graphify query`, atualizar no fim (`graphify update .`).

# Parte B — Requisitos do produto

## Três regras (§6.2)
1. **O teu quarto é teu**: o que passa pela tomada do quarto é do morador (ligação pessoa–quarto vem do contrato).
2. **As zonas comuns são de todos**: por igual (A), com pergunta «de quem é esta conta?» (B, recomendada) ou por presença (C, não implementada). Conta o sítio do aparelho, não o dono.
3. **O sistema avisa do que não bate certo**: orçamento 50/80/100 %, picos em zonas comuns, aparelho pessoal fora do quarto.

Dentro do MVP: energia por tomada, degraus/assinaturas, repartição, plafond solidário, recibos explicados, presença na porta, orçamento, lâmpada RGB como feedback, assistente na app. **Fora** (só com pedido explícito na issue): Telegram/bots, HAN/E-REDES, casa vazia/AWAY e aparelho esquecido (fase 2), reconhecimento facial, gravação de vídeo, MEO Energia, multi-imóvel.

## Regras de domínio
- **Dinheiro:** repartição determinística em código; arredondamentos explícitos; fecho reconciliado a 100 % da fatura. Recibo distingue **medido / estimado / simulado** e é contestável. O senhorio só reparte o custo real da fatura.
- **Lâmpada** não mede: consumo estimado 9 W × tempo × brilho. **Plafond solidário (opcional, por quarto, definido pelo senhorio; 0 = sem plafond):** o aquecimento básico é pago em comum e só o excesso é individual. Sem plafond, cada um paga o seu quarto.
- **Atribuição por aparelho, não por tomada.** Sem identificação nem evidência: divide-se por igual ou só por quem estava em casa. Consumos < ~5 kWh/mês ignorados; o assistente só pergunta quando vale a pena (~0,50 €).
- **Presença** (em casa/fora/incerto): Wi-Fi conta muito a favor e pouco contra; «fora» só após 20–30 min **e** saída pela porta. Um aparelho a continuar ligado não prova presença; só um a ligar prova. Contradição → pergunta, não acusação.
- **«De quem é esta conta?» é votação (D-32)**: um «É minha» basta; atribuir a outra pessoa exige pelo menos metade dos moradores (fecha antes se o próprio assumir); inconclusivo em 24 h → por todos. Fonte única: `confirmation_outcome` em `contracts/notification.py`.
- **Alertas:** orçamento a 50/80/100 % com previsão; pico = zona comum > 1,5 kW durante > 30 min.
- **Assistente IA:** nunca inventa números; tudo vem de ferramentas tipadas, contas em código; ações sensíveis pedem confirmação humana.

# Parte C — Segurança e privacidade (inegociável)
- **Vídeo só local:** nunca gravar, registar ou enviar frames; só a soleira da porta é analisada; sem reconhecimento facial. Só saem eventos («entrou»/«saiu»); visitas só como número. Identidade de presença vem do telemóvel registado (opt-in), nunca da imagem.
- **RBAC:** o senhorio vê totais mensais por quarto e alertas; **nunca** presença, horários, curvas horárias ou imagens. O morador vê os seus dados.
- **Segredos** (`MCP_API_KEY`, tokens OAuth, chaves LLM, URL RTSP) só em `app/.env` e `app/.mcp-auth/` (fora do Git); nunca em logs, erros, testes, issues ou docs.
- **MCP:** leitura `get_home_devices`, `get_device_details` (sensores só em leitura, `unknown` se não suportado); escrita `update_device_capabilities` só em lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`). Nunca alarme, segurança, cenários ou timers sem issue (SAFE-02/04, AGENT-04).
- **Escritas físicas:** `ENABLE_PHYSICAL_WRITES=false` por omissão e grant temporário (MCP-04). Um agente **não executa escritas físicas** sem autorização explícita do utilizador nessa tarefa. Escrita de resultado incerto nunca é repetida: relê-se.
- Nunca inventar resultados, medições, IDs ou confirmações físicas. Distinguir **SIMULADO** (FakeHome, clip, mocks, seed) de **REAL** em UI, docs e pitch.
- Em dúvida sobre segurança, autenticação, privacidade ou hardware: o comportamento mais restritivo.

## graphify
Grafo em `graphify-out/`: perguntas sobre o código começam por `graphify query "<pergunta>"` (também `path`, `explain`). Depois de alterar código: `graphify update .`.
