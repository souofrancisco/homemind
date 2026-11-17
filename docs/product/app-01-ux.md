# APP-01 — Pesquisa UX e shell da Conta Certa

**Estado: DECIDIDO / implementação proposta neste PR.** Issue [#94](https://github.com/souofrancisco/homemind/issues/94). A avaliação abaixo é heurística: não representa entrevistas nem testes com participantes reais. Produto em português de Portugal.

## 1. Auditoria do código antes da alteração

- **KEEP:** React 19, TypeScript, Mantine 9, Vite, Capacitor, OIDC Authentik/PKCE, cliente HTTP com Bearer e redirect no 401, tema automático claro/escuro, componentes acessíveis de Mantine, importação de tipos `components["schemas"]` do OpenAPI gerado.
- **ADAPT (APP-01):** `app/App.tsx`, `routes.tsx`, `components/layout/Shell.tsx`, título do HTML e rótulos de navegação; serviços tipados pelo OpenAPI para membership/casa, notificações, faturas, assistente e diagnóstico.
- **PRESERVAR PARA BASE-04:** `HomeProvider`, `useHome`, páginas antigas `HomePage`, `CameraPage`, `EventsPage`, `AutomationsPage`, `ProfilePage`, mocks e serviços ObjectOS. Não ficam em rotas ativas do novo produto, mas não são apagados nesta issue. A remoção segue `docs/architecture/migration.md`.
- **DEFER:** respostas/votos e preferências de notificações APP-02/03, recibos e alocações APP-05/06, consumo P1/P4 (sem endpoint de produto), catálogo HOUSE-03, conversa APP-06, push Capacitor, branding nativo Android e alterações ao login Authentik. O OIDC permanece intacto.
- **Contratos e APIs implementados:** `MeContext`, casa/divisões, `NotificationView`/`VotingView`, `BillView`, `AgentResponse`, `CameraStatus` e resultados de `GET /api/mcp/tools`. O collector de energia ainda não está montado no barramento e não há endpoint de medições/resumos. Uma casa `source_kind=demo` pode conter medições reais e simuladas: o rótulo da casa **não** é proveniência energética.

## 2. Personas e cinco tarefas prioritárias por papel

| Persona | Tarefas mais frequentes (prioridade de UX, hipóteses a validar) |
|---|---|
| Morador | (1) Ver a sua parte do consumo; (2) responder «É minha / É de todos / Não sei»; (3) consultar recibo e explicação; (4) identificar/registar aparelhos; (5) consultar alertas e orçamento |
| Senhorio | (1) Selecionar casa; (2) ver quartos e contratos; (3) consultar totais mensais agregados; (4) introduzir/fechar faturas; (5) rever alertas de plafond |
| Operador | (1) Selecionar casa de diagnóstico; (2) verificar ligação MCP; (3) verificar leituras e unidade de potência; (4) conferir estado da câmara/dispositivos; (5) preparar/repor demo autorizada |

Os percursos «mais frequentes» são inferidos dos requisitos; não existem métricas de utilização. O senhorio nunca vê presença, imagens, horários, curvas de consumo pessoais ou aparelhos pessoais. O operador não obtém dados financeiros pessoais por defeito.

## 3. Alternativas pesquisadas

### A — Dashboard-first

- **IA:** Início (estado/consumo/orçamento) → Consumo → Contas → Casa/Aparelhos → Notificações/Assistente → Definições.
- **Desktop:** sidebar fixa por secções + cabeçalho com contexto da casa. **Mobile:** 4 destinos principais no fundo + «Mais» para secundários.
- **Wireframe textual:**

```text
[Casa escolhida]                  [Alertas]
[Consumo pessoal] [Orçamento]     [Pendentes]
[Consultar recibo] [Ver aparelhos]
[Histórico recente]               [Navegação lateral]
```

- **Confirmar consumo:** Início → pendência → Notificações → detalhe → resposta → confirmação do servidor.
- **Consultar conta:** Início → Contas → mês → recibo → justificação.
- **Gerir aparelhos:** Início → Aparelhos → catálogo → associar ao quarto/aparelho (futuro).
- **Prós:** mostra imediatamente valor, bom palco para demonstração e orçamentos; **contras:** depende muito de dados que hoje não existem; dashboard vazia é fraca.
- **Complexidade:** média/alta; muitos cartões e estados. **Acessibilidade:** deve evitar cartões clicáveis ambíguos, usar headings e leitura linear. **Evolução:** alta para analytics; médio para gestão espacial.
- **Hackathon:** muito forte quando a vertical de telemetria e fatura estiver ligada; frágil em demo sem dados.

### B — House-first

- **IA:** Início → Casa (contexto) → Divisões, moradores, aparelhos → Consumo → Contas → Notificações/Assistente → Definições.
- **Desktop:** sidebar persistente e contexto da casa/papel em cabeçalho. **Mobile:** barra inferior curta e menu «Mais».
- **Wireframe textual:**

```text
[Selecionar casa]    [Papel atual]
[A minha casa]
[Quartos] [Zonas comuns]
[Consumo] [Contas] [Aparelhos permitidos]
```

- **Confirmar consumo:** Casa atual → Notificações → pedido da casa → verificar dados → responder → confirmação do servidor.
- **Consultar conta:** Casa atual → Contas e recibos → período → detalhe permitido por papel.
- **Gerir aparelhos:** Casa → Aparelhos → visualizar próprios ou diagnóstico técnico (nunca aparelhos pessoais para senhorio).
- **Prós:** reforça propriedade, quarto, origem da despesa e privacidade por casa; **contras:** adicionar uma etapa espacial a tarefas financeiras.
- **Complexidade:** média; um contexto de casa reutilizável. **Acessibilidade:** contexto e papel explicitados textualmente, títulos consistentes. **Evolução:** excelente para múltiplas casas, quartos, contratos, permissões.
- **Hackathon:** muito forte a explicar a regra «quarto / comum» e a separação de papéis.

### C — Activity-first

- **IA:** Atividade/Pendentes → Consumos → Notificações → Contas → Casa/Aparelhos → Definições.
- **Desktop:** lista de atividade/pedidos com painel de detalhe. **Mobile:** inbox como primeira vista; navegação por separadores.
- **Wireframe textual:**

```text
[Pendentes  |  Resolvidos]
[Pedido: de quem foi o consumo?]
[Evento com origem e confiança]
[Atribuição] [Conta do mês]
```

- **Confirmar consumo:** abre a app → pedido → origem/impacto → «É minha / É de todos / Não sei» → backend confirma.
- **Consultar conta:** Atividade → evento de fatura → Conta → recibo.
- **Gerir aparelhos:** Atividade → menu Casa/Aparelhos → catálogo.
- **Prós:** excelente para confirmar e contestar; **contras:** perde explicação global da casa e depende de feed real.
- **Complexidade:** média/alta por estados, deduplicação, filtros, acessibilidade de lista. **Evolução:** forte para eventos e notificações; média para onboarding.
- **Hackathon:** funciona bem como passo específico da demo, menos bem como ecrã inicial universal.

### Matriz de decisão (escala 1–5; avaliação heurística)

| Critério | Peso | A | B | C |
|---|---:|---:|---:|---:|
| Clareza para o morador | 25% | 5 | 5 | 4 |
| Privacidade e múltiplos papéis | 25% | 4 | 4 | 4 |
| Demonstração da proposta de valor | 20% | 5 | 5 | 4 |
| Independência de módulos ainda ausentes | 15% | 3 | 5 | 3 |
| Simplicidade de implementação | 10% | 4 | 4 | 3 |
| Evolução futura | 5% | 4 | 4 | 3 |
| **Total ponderado** | **100%** | **4,30** | **4,60** | **3,70** |

**Decisão:** **B (House-first) com abertura de A (Dashboard-first) e uma área de atividade de C**. A casa e a membership são o contexto obrigatório; o Início é útil sem telemetria e evolui sem troca de navegação; Notificações recebem apenas os pedidos pessoais do backend quando P3 estiver disponível.

### Referências e princípios utilizados

- [Mantine AppShell](https://mantine.dev/core/app-shell/): nav responsive com navbar e footer.
- [Android Developers — navegação adaptativa](https://developer.android.com/develop/ui/views/layout/build-responsive-navigation): navegação inferior em telas estreitas, barra/lateral para mais espaço.
- [NN/g — Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/): esconder complexidade secundária sem ocultar a tarefa principal.
- [Octopus Energy — acompanhar consumo](https://octopus.energy/blog/track-my-energy-use/): consumo por período, gastos e contas em áreas distintas.
- [Splitwise — utilização de grupos](https://kb.splitwise.com/getting-started/how-do-i-use-splitwise): grupo/casa como contexto para despesas partilhadas.

Estas fontes são referências de padrões, não demonstração de testes de usabilidade da Conta Certa.

## 4. Estrutura implementada pelo shell

```text
Conta Certa (contexto do /api/me/context)
├── Início                   [tenant, landlord, operator] — resumo sem números fictícios
├── A minha casa             [tenant, landlord, operator] — casa e divisões reais da API
├── Consumo                  [tenant, landlord]           — sem endpoint ENERGY de leitura
├── Aparelhos                [tenant, operator]           — HOUSE-03 aberto, sem API de catálogo
├── Contas e recibos         [tenant, landlord]           — lista BillView real; sem recibos/alocações REST
├── Notificações             [tenant, landlord]           — lista real; respostas/votos APP-02/03
├── Assistente               [tenant]                     — endpoint real SIMULADO; interface APP-06
├── Diagnóstico              [operator]                   — MCP tools + estado resumido da câmara
└── Definições               [todos]                      — contexto/papel e logout
```

- Barra lateral desktop; no mobile, destinos principais no fundo e secundários acessíveis por «Mais». Foco visível, skip-link, headings, texto alternativo a ícones, `aria-current` e tamanhos táteis.
- Todas as rotas passam por `AuthProvider` existente. O novo `HouseholdProvider` consulta `/api/me/context` com o cliente HTTP partilhado, e nunca assume um papel a partir de um seletor arbitrário.
- `/api/households/{id}` e `/rooms` só carregam para a membership selecionada; os dados de outra casa não são reutilizados durante uma mudança de contexto.
- Acesso direto a uma rota sem papel autorizado redireciona para o Início. Isto **não** substitui `require_access` no FastAPI.
- Estados explícitos: loading do contexto, erro com tentativa novamente, casa sem divisões, conta sem membership, módulo por integrar. Qualquer falha da API mantém dados privados fora da interface. O indicador «casa demo» não rotula medições.
- Não existem caixas de resposta para notificações, chat, recibos fictícios ou controlos IoT sem backend.
- Sem integração de Telegram, sem novas dependências ou alteração de contratos.

## 5. Matriz de integração confirmada na `origin/main`

| Página | Backend real disponível | PR/issue | Permissões | O que falta | Decisão UX |
|---|---|---|---|---|---|
| Início | `GET /api/me/context`, `/api/households/{id}` e `/rooms` | HOUSE-02 #143 merged | Membership ativa; papéis tenant/landlord/operator | Sem endpoint de resumo de energia | Mostrar casa e atalhos sem números fictícios |
| A minha casa | Contexto, casa, divisões e memberships | #143 merged | Morador/senhorio; operador só diagnóstico de casa/quartos; o backend decide | HOUSE-05 para convites/UI de gestão | Mostrar apenas o quarto próprio ao morador e divisões autorizadas |
| Consumo | Collector interno produz `EnergyReading`, mas ainda não está ligado ao barramento nem exposto por REST | MCP-02 #139 merged; ENERGY-01/02/03/05 pendentes | Contrato prevê agregado para senhorio e próprio para morador; sem endpoint disponível | Motores ENERGY, montagem do collector, leituras/resumos REST | Placeholder factual; não mostrar leituras nem totais inferidos |
| Aparelhos | `DeviceView` existe no OpenAPI, sem rotas de catálogo; medidor físico é `Device`, consumidor é `Appliance` | HOUSE-03 #86 / PR #142 aberto; HOUSE-04 #87 / PR #145 draft | A matriz prevê aparelho próprio para morador e diagnóstico para operador; senhorio não recebe aparelhos | Catálogo temporal e endpoints HOUSE-03; políticas de atribuição HOUSE-04 | Não consultar nem misturar aparelhos com medidores; não inferir pagador |
| Contas e recibos | `GET /api/households/{id}/bills` e `GET .../bills/{bill_id}` devolvem `BillView`; `POST .../bills` grava rascunho; `POST .../bills/preview` valida sem gravar | BILL-01 #89 / PR #163 merged; BILL-02 #90 / PR #152 merged; BILL-04 #92 / PR #162 merged | Senhorio vê todos os estados; morador recebe só `finalized`; operador `403` | Sem endpoints de finalizar fatura, ler alocações/recibo ou contestar nesta API | Lista só `BillView`; UI não calcula repartições e respeita filtro de rascunhos do servidor |
| Notificações | GET/lista, read, respond e preferências por casa | APP-02 #95 / PR #156 merged; APP-03 #96 / PR #161 merged | Morador vê as suas e da casa; senhorio só allow-list informativa (atual `info`); operador `403` | UI detalhada e produtores de orçamento/pico; WebSocket planeado | Lista de leitura usa `NotificationView`/`VotingView`; sem botões até UI de votação APP-02/03 |
| Assistente | `POST /api/households/{id}/agent/messages` → `AgentResponse` | AGENT-01/02 #110 / PR #154 merged | Só morador; senhorio/operador `403` | Providers reais, histórico e interface APP-06; hoje dados da demo são SIMULADOS, LLM desligado por omissão, `proposed_actions=[]` | Indicar disponibilidade da API e limites; sem outro LLM nem ferramentas de escrita |
| Diagnóstico | `GET /api/mcp/tools`; `GET /api/presence/camera/status` | MCP existente; PRES-01; guarda de operador corrigida neste PR | Só operador após guarda backend; nenhum preview visual | Energia/medidor não tem endpoint de estado | Mostrar lista de ferramentas e estado resumido da câmara; nunca frames, preview ou comandos |
| Definições | OIDC/AuthProvider existentes e memberships de `/api/me/context` | Authentik herdado; HOUSE-02 #143 | Sessão e papel determinados no servidor | Preferências de conta gerais não existem | Manter logout; sem recriar autenticação |

### Presença e limites de privacidade

PRES-03 #107 / PR #153 e PRES-04 #108 / PR #159 estão merged. A API atual serve `PersonPresence` e dispositivos Wi-Fi apenas ao próprio morador (`tenant`, `Resource.presence=own`); não existe hoje `PUT /api/presence/me` para check-in manual. Senhorio e operador recebem `403`. `GET /api/presence/camera/status` é diagnóstico de operador e não contém imagem; `/api/video` é operador, está desligado por omissão e não é usado pela UI. Não há rota de presença no menu da APP-01.

D-32 prevalece no endpoint de resposta: «É minha» pode decidir com um voto; atribuir a outra pessoa exige maioria de pelo menos metade; sem decisão até ao prazo ou com todos a votar sem decisão, fica para a casa. A shell mostra apenas os totais anónimos em `VotingView`; nenhuma UI desta issue envia resposta.

## 6. Auditoria UX e acessibilidade

- **Implementado e revisto no código:** sidebar desktop; footer móvel com “Mais”; skip-link; `aria-current`; headings; nome de papel e contexto de membership; loading/erro/vazio; títulos do documento; anúncio `aria-live` de rota; o seletor só oferece memberships devolvidas pelo backend.
- **Isolamento:** casa selecionada vem de membership; conteúdo carregado fica associado ao `household_id`; ao trocar de membership o provider e as páginas não renderizam o estado guardado de outra casa enquanto a nova resposta não chega. Guards da UI são conveniência: RBAC continua no backend.
- **Mobile:** o footer mantém quatro destinos principais no máximo e agrupa os restantes; “Mais” fica destacado quando a página ativa está no grupo secundário. O seletor de casa tem largura compacta e rótulo acessível.
- **Projetor:** a largura desktop usa o layout existente e mantém títulos/texto; o percurso de operador foi aberto a 1920×1080 com fixture. Não há um modo de projeção separado.
- **WCAG 2.2 AA:** o código oferece foco nativo Mantine, skip-link, navegação por teclado, labels e estados sem depender só de cor. Contraste medido, zoom 200%, leitor de ecrã, alvos em hardware e ausência de overflow ainda precisam de validação em browser; não declarar conformidade AA sem essa evidência. Esta shell não abre modais; trapping de foco não aplicável.
- **Movimento:** a regra CSS local remove transição do skip-link com `prefers-reduced-motion`; não foi feita validação visual de todas as transições Mantine.
- **Autenticação:** Authentik/OIDC/PKCE, logout, renovação silenciosa, 401 e deep links Capacitor mantêm o provider existente; nenhum login real foi executado nesta revisão.

## 7. Próximas integrações

- **APP-02/03:** lista de notificações, ações e preferências completas; tratar `409 already_responded`/`notification_expired`; implementar D-32 como votação e jamais primeira resposta vence; só confirmar sucesso após resposta do backend.
- **APP-05/06:** usar `BillView`, `BillPreview`, contratos de alocação/recibo quando houver rotas; apresentar rascunhos só ao senhorio; nenhuma repartição/calculadora frontend; ligar assistente a `AgentResponse` mantendo SIMULADO explícito.
- **ENERGY/P1 + BILL/P4:** publicar/consultar leituras e alocações por API com proveniência individual; não tratar `DeviceView`/`EnergyReading` no schema como prova de endpoint implementado.
- **HOUSE-03/04:** esperar merge do catálogo e políticas de atribuição; diferenciar `Device` de `Appliance`; autorização e pagador nunca são inferidos no cliente.
- **PRES/P2:** UI futura só consulta a presença do próprio morador; nunca mostrar estado ou histórico individual a senhorio; não adicionar preview de vídeo.

## 8. Validação e limites

### Checklist manual obrigatória (não confundir com testes já executados)

1. **Autenticação web:** sessão expirada e redirecionamento OIDC; regresso à rota; logout; 401.
2. **Android/Capacitor:** login por navegador do sistema e deep link; sem token no URL da API.
3. **Papéis:** três contas reais (tenant, landlord, operator); comparar rotas visíveis e tentar URL direto (incluindo refresh); confirmar 403/404 no servidor.
4. **Isolamento:** utilizador com duas casas; alternar várias vezes; nenhuma informação anterior deve surgir no novo contexto.
5. **Origem:** demo / produção são etiquetas da casa, nunca prova de `measured`; não apresentar zero na ausência de leitura.
6. **Desconexão e falhas:** API indisponível, respostas 401/403/500, sem membership, sem quartos, demora da API; verificar loading/erro e recuperação.
7. **Acessibilidade:** tab, shift-tab, Enter/Espaço, skip-link, foco, zoom 200%, leitor de ecrã; sem ações ocultas.
8. **Tamanhos:** 320, 375, 768, 1280 e 1920 px; header/footer não tapam conteúdo; 1920×1080 em projetor.
9. **Modo escuro/claro e redução de movimento:** contraste, labels e sem dependência da cor.
10. **Integração:** `make check` e CI do Draft PR; fixtures browser cobrem apenas apresentação/estados e não substituem sessões autenticadas.

**Validação desta revisão:** `make check`, `make smoke` (stack local incluindo Authentik) e testes de autorização de API passaram. Playwright com fixtures de OIDC/API cobriu morador, senhorio, operador, sem membership, API indisponível, troca de casa, foco inicial por teclado, mobile a 320 px, desktop e projetor a 1920×1080; não representa autenticação real nem prova permissões do servidor além dos testes de API. Screenshots locais em `/tmp/app-01-shots/` (não versionadas). Login/logout interativo, sessão expirada, leitor de ecrã, zoom 200%, contraste e Android não foram verificados. Authentik não foi usado para uma sessão interativa. APP-05/06 e APP-02/03 continuam donos dos fluxos detalhados.
