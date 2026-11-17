# Estado para amanhã — auditoria de 17/11/2026

Resultado da auditoria, endurecimento e consolidação da documentação. Publicado num único commit na `main`: `refactor: harden ObjectOS, consolidate docs and prepare validation`.

- **Base:** `8217368` (`origin/main` antes da auditoria).
- **SHA final:** `git log -1 --format=%H -- docs/estado-para-amanha.md` (um commit não pode conter o seu próprio hash).

Cada afirmação está classificada: **FACTO VERIFICADO**, **PRESSUPOSTO**, **RESULTADO REAL**, **RESULTADO SIMULADO** ou **BLOQUEIO EXTERNO**.

## 1. Resumo

| Área | Estado |
|---|---|
| Arranque em FakeHome (`make dev`) | FACTO VERIFICADO: `make smoke` passa; login real no Authentik e API validados |
| Motor, regras, WebSocket | RESULTADO SIMULADO: ponta a ponta em processo real com FakeHome, 4 rondas sem falhas |
| Visão → gestos → motor | RESULTADO SIMULADO: clip sintético + detetor falso; YOLO real não exercitado nesta auditoria |
| MCP: OAuth, descoberta, leituras, polling | RESULTADO REAL: só leituras, 18/18 verificações |
| MCP: controlo físico da lâmpada/tomada | BLOQUEIO EXTERNO: não comprovado (ver §6) |
| Consumo em W | BLOQUEIO EXTERNO: unidade não declarada pelo MCP |
| NVIDIA | Não verificado (sem chave no ambiente da auditoria) |

## 2. Alterações implementadas

### Correções (com testes)

| # | Problema encontrado | Correção | Prova |
|---|---|---|---|
| 1 | **Escrita MCP fantasma.** Um pedido feito enquanto a sessão MCP falhada ainda fechava ficava numa fila que ninguém lia: o chamador esperava até 25 s por um timeout e o pedido podia ser executado **mais tarde** pela sessão seguinte (por exemplo, ligar a lâmpada depois de «Desligar tudo»). | `connectors/mcp_home.py`: a sessão deixa de ser a corrente antes de fechar; pedidos cujo chamador desistiu são descartados; um pedido interrompido pelo encerramento falha de imediato. | 2 testes novos que falham sem a correção |
| 2 | A releitura depois de uma escrita falhada demorava 19 s com o `McpHome` bloqueado (mesma causa). | Idem. | idem |
| 3 | O MCP responde «device updated» sem efeito físico e a mensagem de falha não ajudava a perceber porquê. | A falha passa a indicar há quantos minutos o dispositivo não contacta a cloud. Só diagnóstico; nunca repete escritas. | 1 teste novo |
| 4 | `pytest` não corria no CI (`make check` não incluía testes). | `make check` = lint + **testes** + contratos + build + compose. | `make check` verde, 199 testes |
| 5 | Os logs INFO da aplicação perdiam-se (o uvicorn só configura os seus loggers): «visão ligada» e os tempos das escritas MCP nunca apareciam. | `main.py` configura o logger `homemind`. | visto no log do teste ao vivo |
| 6 | Erros não previstos respondiam texto simples, fora do formato de erro; pedidos inválidos não diziam que campo estava errado. | `core/errors.py`: `500 internal_error` no envelope, sem detalhes; `400` indica os campos (nunca os valores). | 2 testes novos |
| 7 | `/healthz` reportava `mode: "simulation"` (herança do projeto anterior) mesmo com dispositivos reais. | Passa a `backend: "fake" \| "mcp"`. | teste atualizado, verificado ao vivo |
| 8 | Tarefas do motor canceladas mas não aguardadas no encerramento; a casa ficava a correr se o motor falhasse ao arrancar. | `lifespan` do motor aguarda as tarefas e limpa sempre. | encerramento limpo em < 1 s, sem avisos |
| 9 | Leitura do JWKS sem limite de tempo útil (30 s por omissão). | Timeout de 5 s. | — |
| 10 | Configuração morta: `APP_MODE`, `DATABASE_PATH`, `MCP_TRANSPORT`, `LLM_API_KEY`. | Removida do código, do Compose e do `.env.example`. Ficheiros `.env` antigos continuam válidos (variáveis extra são ignoradas). | `make smoke` |
| 11 | Título da API «HomeMind Spaces API»; comentários a apontar para documentos e módulos inexistentes. | Corrigidos. | — |

### Melhorias de utilização

- `make auth`: sobe só o Authentik, para correr backend (com YOLO) e frontend no host.
- `make mcp-doctor`: além de `tools/list`, mostra estado e último contacto da lâmpada e da tomada, sem IDs.
- `app/.env.example` reorganizado; arranca em modo simulado sem edição.

### Documentação

README, `CLAUDE.md`, `AGENTS.md` (raiz, backend, frontend) e todos os documentos de `docs/` reescritos ou atualizados para o estado real. `docs/contratos.md` é agora o contrato canónico único.

## 3. Ficheiros eliminados ou movidos

| Ficheiro | Motivo | Informação preservada em |
|---|---|---|
| `frontend-api-contract.md`, `frontend-api-contract-novo.md`, `frontend-api-contract-v3.md` (raiz), `docs/frontend-api-contract.md` | Quatro versões concorrentes do mesmo contrato, todas marcadas «proposta» | `docs/contratos.md` |
| `docs/objectos-frontend-extensions.md` | Proposta desatualizada (descrevia o frontend sem WebSocket autenticado) | `docs/contratos.md` §4 |
| `motor-arranque-p2.md` | Nota de arranque já refletida no código | `docs/contratos.md` §1, `app/backend/AGENTS.md` |
| `docs/assumptions.md`, `docs/report-outline.md` | Conteúdo do projeto anterior (estadias) | — |
| `docs/decisions/0001`, `0002` | Duas linhas cada | `docs/architecture.md` («Decisões») |
| `Desafio#3_Altice_Hackathon_MCP_ATC2026.pdf` → `docs/altice-mcp-guia-ligacao.pdf` | **Movido, não eliminado**: é o guia oficial de ligação ao MCP | — |

Tudo continua no histórico Git. Os ficheiros não versionados `docs/frontend-api-contract*.md` no worktree `feat/issue-24-objectos-dashboard` não foram tocados; são cópias das versões agora substituídas e podem ser apagados.

## 4. Arquitetura e organização

Sem mudanças estruturais: a arquitetura por features já era adequada. Ver `architecture.md` (diagramas) e `contratos.md`.

Decisões de auditoria:

- **Mantido** o arranque por `lifespan` de cada router, pela ordem alfabética das features. Funciona, está testado ao vivo e documentado; centralizar em `main.py` seria uma refatoração sem ganho para o MVP.
- **Mantidos** os nomes internos `homemind` (pacote, cliente OIDC, projeto Compose, id Android): renomear arrisca o login e os volumes de toda a equipa.

## 5. Testes executados

| Verificação | Resultado | Tipo |
|---|---|---|
| `make check` (ruff, eslint, pytest, OpenAPI→TS, build, compose) | passa; 199 testes (194 antes + 5 novos) | FACTO VERIFICADO |
| `pytest` repetido 3× | 199/199 em todas; sem falhas intermitentes | FACTO VERIFICADO |
| `make smoke` (stack Docker isolada) | `smoke OK`, 2 execuções | FACTO VERIFICADO |
| Backend real + FakeHome: 401 (sem token, expirado, audiência e emissor errados), REST, erros, WebSocket (auth, 1008, snapshot, reconexão), modos, espera → aviso → suspensão → regresso, poupança, desligar tudo, encerramento, ausência de segredos no log | 26/26 em 4 rondas | RESULTADO SIMULADO (FakeHome; tokens de um IdP de teste local) |
| Clip → thread de visão → gesto → motor → `home_state`; MJPEG autenticado | 16/16 em 2 rondas | RESULTADO SIMULADO (clip sintético, detetor falso) |
| Authentik isolado: login `akadmin` com Authorization Code + PKCE, token aceite por `/api/me` e `/api/state` | passa | RESULTADO REAL |
| Backend com `HOME_BACKEND=mcp`, escritas desativadas: `mcp_ok`, estados lidos, `/api/mcp/tools` (18 ferramentas), `/api/simulate` → 403, `/api/off` recusado sem enviar nada, polling estável | 18/18 | RESULTADO REAL, só leituras |
| `make mcp-doctor` (novo diagnóstico) | passa | RESULTADO REAL, só leituras |

**Não foi executado:** nenhuma escrita física; YOLO real (extra `visao` não instalado); câmara RTSP; NVIDIA; interface no browser; Android.

## 6. Estado do MCP

**RESULTADO REAL (leituras de 17/11, noite):**

- OAuth, sessão persistida, `initialize`, `tools/list` e leituras funcionam. Abrir sessão ~0,8 s; leitura 0,65–0,87 s.
- Uma lâmpada RGB e uma tomada identificadas sem ambiguidade.
- Lâmpada: `power: on`, `workMode: colour`, brilho 18. **Último contacto com a cloud: 14 min, depois 32 min** (a aumentar entre leituras). Tomada: 69 e 87 min.

**A lâmpada não reagiu ao último controlo.** A causa não está determinada. Hipóteses, por ordem de probabilidade (detalhe e forma de confirmar em `mcp-capabilities.md`):

1. **H1 — a lâmpada não está a comunicar com a cloud.** A evidência mais forte: `lastCommunicationTime` sempre antigo e a aumentar, e a releitura a voltar ao estado inicial. O MCP aceita a escrita na mesma.
2. H2 — a escrita é assíncrona e mais lenta do que a janela de confirmação.
3. H3 — `color_rgb` só tem efeito em `workMode: colour`.
4. H4 — o servidor precisa de `vendor` para encaminhar o comando.
5. H5 (tomada) — `power` não atua no interruptor `switch_1` do `multiPower`.

**Possível contributo do nosso código (corrigido):** o defeito n.º 1 da §2 podia fazer com que uma escrita pedida logo a seguir a uma leitura falhada nunca fosse enviada. Não há evidência de que tenha sido a causa da última tentativa (a verificação documentada mostra a resposta «device updated»), mas fica eliminado.

**Primeiro passo amanhã:** `make mcp-doctor` e ler a linha «Lâmpada: … último contacto há N min». Comandar a lâmpada pela app oficial e repetir. Se N não descer, o problema é a ligação da lâmpada, não o ObjectOS.

## 7. Falhas e limitações conhecidas (não corrigidas)

| Limitação | Impacto | Porque ficou |
|---|---|---|
| Se a regra do modo ativo for substituída ou apagada, o modo em curso mantém a versão antiga até ao próximo gesto | baixo | alteração de comportamento do motor sem necessidade para a demo |
| O painel só recupera os últimos 50 eventos em memória; depois de reiniciar o backend o histórico visível começa vazio (o `events.jsonl` mantém tudo) | baixo | comportamento documentado no contrato |
| A poupança é uma estimativa desde o arranque do servidor | médio (pitch) | por desenho; dizer sempre «estimativa» |
| Com MCP a poupança fica a zero | médio | BLOQUEIO EXTERNO: unidade de `instantPower` |
| Host e container partilham o ficheiro de tokens; se o servidor rodar o refresh token, o backend pode mostrar o aviso de sessão expirada durante um ciclo e recuperar sozinho | baixo | documentado em `mcp-demo.md` §8 |
| O log de erros não previstos do uvicorn inclui o traceback completo | baixo | útil para depurar; não partilhar logs em bruto |
| Sem testes automáticos de frontend | médio | fora do âmbito; coberto pelo guia manual (UI-01, UI-02) |
| App Android ainda se chama «HomeMind» | cosmético | renomear mexe em ficheiros nativos |
| Issues #10 e #11 estão fechadas, mas o controlo físico não está comprovado | organização | não se fecham nem reabrem issues automaticamente |

## 8. Pressupostos adotados

| # | O que se assumiu | Porquê | Evidência | Risco | Como confirmar |
|---|---|---|---|---|---|
| 1 | O PDF na raiz é o guia oficial de ligação ao MCP e deve ser mantido | É referência oficial da organização | conteúdo lido (configuração VS Code/Hermes/Codex) | nenhum | — |
| 2 | Ninguém consumia o campo `mode` de `/healthz` | Substituído por `backend` | pesquisa no frontend, Makefile e Compose: só `status` é lido | scripts pessoais que leiam `mode` | `grep -r '"mode"'` em scripts próprios |
| 3 | As variáveis de configuração removidas não eram usadas | Limpeza | pesquisa em todo o repositório | nenhum (extra no `.env` é ignorado) | `make dev` com o `.env` antigo |
| 4 | `lastCommunicationTime` é o último contacto do dispositivo com a cloud, em ms | Usado só como diagnóstico | valor em epoch ms, coerente com a hora atual | interpretação errada da mensagem | pergunta 3 aos mentores |
| 5 | O utilizador de desenvolvimento do Authentik é `akadmin` / `homemind-dev` | Escrito no README | login real executado numa stack isolada | muda se `AUTHENTIK_ADMIN_PASSWORD` estiver definido | AUTH-01 |
| 6 | Prazos: resumo PDF a 18/11 19h00, apresentação a 20/11 17h30 | Vinham dos documentos anteriores, que não coincidiam entre si | só documentos internos | prazo errado | confirmar com a organização **hoje** |
| 7 | A ordem alfabética dos `lifespan` é aceitável como mecanismo de arranque | Evitar refatoração | testado ao vivo | uma feature nova com nome antes de `engine` | regra em `app/backend/AGENTS.md` |
| 8 | Incluir `pytest` no CI não atrasa a equipa | 199 testes em ~10 s, sem rede | medido | nenhum | — |
| 9 | O painel funciona no browser como antes | Nenhum ficheiro do frontend foi alterado | lint, build e `make smoke` passam | regressão visual improvável | UI-01 |

## 9. Perguntas para os mentores

Lista completa em `mentor-questions.md`. As três que desbloqueiam mais:

1. A lâmpada está online na cloud? O que significa `lastCommunicationTime` e porque está a aumentar?
2. `update_device_capabilities` é assíncrono? Precisa de `vendor`? `color_rgb` depende de `workMode`?
3. Qual é a unidade de `instantPower`?

## 10. Comandos

```bash
# Modo simulado (sem hardware)
cp app/.env.example app/.env && make dev        # http://localhost:5173 — akadmin / homemind-dev

# Verificações
make check && make smoke

# MCP só leitura
make mcp-login && make mcp-doctor && make mcp-demo

# Visão real no host (três consolas)
make auth
cd app/backend && uv sync --extra visao && uv run python -m homemind.features.visao.pesos \
  && uv run --env-file ../.env uvicorn homemind.main:app --host 0.0.0.0 --port 8000
cd app/frontend && npm ci && npm run dev
```

## 11. Prioridades para amanhã

1. **Lâmpada (P0):** `make mcp-doctor`, app oficial, mentores → MCP-03 e MCP-04 do guia.
2. **Câmara e visão reais (P0):** VID-01 a VID-03, YOLO-01, YOLO-02; decidir o objeto do «livro» e a variante do modelo.
3. **Gestos no clip MEARI (P0):** gravar o clip, afinar com o afinador, GES-01, GES-02, PRE-01.
4. **Latência e 10 demos (P0):** LAT-01, DEMO-01; LAT-02 só se a lâmpada funcionar.
5. **Plano B ensaiado (P1):** PB-01, com o tempo de troca cronometrado.
6. **Consumo (P1):** MCP-06 com carga conhecida.
7. **Entregáveis (P1):** resumo PDF, PPT, pitch — confirmar prazos primeiro.

## 12. Checklist da demonstração

- [ ] `make check` e `make smoke` verdes no commit da demo
- [ ] Folha de resultados do guia preenchida nesse dia
- [ ] `PROFILE=demo`; sessão iniciada antes de entrar; portátil na corrente
- [ ] Câmara enquadrada; caneca, livro (ou substituto) e comando na mesa
- [ ] Modo MCP: `make mcp-doctor` com último contacto recente; escritas autorizadas pelo tempo da demo
- [ ] Plano B pronto: clip MEARI e `HOME_BACKEND=fake`, ensaiados
- [ ] Guião só afirma como REAL o que tem PASS REAL
- [ ] `make mcp-writes-off` no fim

## 13. Issues pendentes

| Issue | Falta |
|---|---|
| #4 YOLO | clip MEARI real, fiabilidade do livro, FPS em GPU |
| #5 Gesto | 10/10 e 0 falsos positivos no clip real |
| #8 Afinador | afinação com o clip real |
| #12 Consumo | unidade de `instantPower` (bloqueio externo) |
| #28 Integração | latência real, 10 demos seguidas |
| #29 Entregáveis | PDF, PPT, pitch |
| #30, #31 Extras | não começar |
| (#10, #11 fechadas) | controlo físico da lâmpada e da tomada por comprovar |
