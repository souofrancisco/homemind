# APP-01 — Pesquisa UX e shell da Conta Certa

**Estado: DECIDIDO / implementação proposta neste PR.** Issue [#94](https://github.com/souofrancisco/homemind/issues/94). A avaliação abaixo é heurística: não representa entrevistas nem testes com participantes reais. Produto em português de Portugal.

## 1. Auditoria do código antes da alteração

- **KEEP:** React 19, TypeScript, Mantine 9, Vite, Capacitor, OIDC Authentik/PKCE, cliente HTTP com Bearer e redirect no 401, tema automático claro/escuro, componentes acessíveis de Mantine, importação de tipos `components["schemas"]` do OpenAPI gerado.
- **ADAPT (APP-01):** `app/App.tsx`, `routes.tsx`, `components/layout/Shell.tsx`, título do HTML e rótulos de navegação; novos componentes pequenos de apresentação e serviço tipado para `/api/me/context`, `/api/households/{id}` e `/rooms`.
- **PRESERVAR PARA BASE-04:** `HomeProvider`, `useHome`, páginas antigas `HomePage`, `CameraPage`, `EventsPage`, `AutomationsPage`, `ProfilePage`, mocks e serviços ObjectOS. Não ficam em rotas ativas do novo produto, mas não são apagados nesta issue. A remoção segue `docs/architecture/migration.md`.
- **DEFER:** centro de notificações e ações P3, consumo P1/P4, faturação e recibos APP-05/06, catálogo HOUSE-03, assistente P3, push Capacitor, branding nativo Android e alterações no login Authentik. O OIDC permanece intacto.
- **Contratos implementados:** `MeContext` contém memberships ativas e o residente; `HouseholdView` contém `source_kind`, `RoomView` contém `name/kind`. Não existe endpoint de métricas da Conta Certa validado para usar nesta shell. Uma casa `source_kind=demo` pode conter medições reais e simuladas: o rótulo da casa **não** é proveniência energética.

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
| Privacidade e múltiplos papéis | 25% | 4 | 5 | 4 |
| Demonstração da proposta de valor | 20% | 5 | 5 | 4 |
| Independência de módulos ainda ausentes | 15% | 3 | 5 | 3 |
| Simplicidade de implementação | 10% | 4 | 4 | 3 |
| Evolução futura | 5% | 5 | 5 | 4 |
| **Total ponderado** | **100%** | **4,35** | **4,90** | **3,80** |

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
├── Consumo                  [tenant, landlord]           — P1/P4 por integrar
├── Aparelhos                [tenant, operator]           — HOUSE-03 por integrar
├── Contas e recibos         [tenant, landlord]           — APP-05/06 por integrar
├── Notificações             [tenant, landlord]           — P3 por integrar
├── Assistente               [tenant]                     — P3 por integrar
├── Diagnóstico              [operator]                   — técnico por integrar
└── Definições               [todos]                      — contexto/papel e logout
```

- Barra lateral desktop; no mobile, destinos principais no fundo e secundários acessíveis por «Mais». Foco visível, skip-link, headings, texto alternativo a ícones, `aria-current` e tamanhos táteis.
- Todas as rotas passam por `AuthProvider` existente. O novo `HouseholdProvider` consulta `/api/me/context` com o cliente HTTP partilhado, e nunca assume um papel a partir de um seletor arbitrário.
- `/api/households/{id}` e `/rooms` só carregam para a membership selecionada; os dados de outra casa não são reutilizados durante uma mudança de contexto.
- Acesso direto a uma rota sem papel autorizado redireciona para o Início. Isto **não** substitui `require_access` no FastAPI.
- Estados explícitos: loading do contexto, erro com tentativa novamente, casa sem divisões, conta sem membership, módulo por integrar. Qualquer falha da API mantém dados privados fora da interface. O indicador «casa demo» não rotula medições.
- Não existem caixas de resposta para notificações, chat, recibos fictícios ou controlos IoT sem backend.
- Sem integração de Telegram, sem novas dependências ou alteração de contratos.

## 5. Validação e limites

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
10. **Integração:** `make check` e CI do Draft PR; screenshots somente se houver navegador da aplicação autenticado no ambiente de teste.

**Limitação intencional:** este PR é *shell* e não testa fluxos financeiros, notificações interativas ou telemetria. APP-05/06 e P3 substituem placeholders na sua própria implementação.
