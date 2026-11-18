# Fluxos funcionais verificados

Só fluxos **comprovados**. Estado: **Browser** = percorrido com Playwright/Chromium contra a demo (SIMULADA); **Testes** = coberto por `pytest` mas não visto no browser; **Hardware** = nunca validado. Evidência e datas: [`evidence/demo-web-2026-11-18/`](evidence/demo-web-2026-11-18/README.md). Nada aqui foi validado com hardware real.

| Fluxo | Entrada | Componentes | Resultado | Estado | Limitações |
|---|---|---|---|---|---|
| **Autenticação e casa** | login Authentik (OIDC + PKCE) | Authentik → `features/auth` (JWT) → `households` (`sub` → membership) | Início do papel certo; casa «Casa da Rua Direita (demo)» | Browser | Contas só no Authentik local; verificação de email real bloqueada (#85) |
| **Permissões por papel** | token de cada conta | `core/access.py`, routers | morador: dados próprios; senhorio: totais por quarto, 403 em recibo pessoal/presença/aparelhos; operador: dispositivos | Browser + HTTP | Matriz testada por amostra, não exaustiva |
| **Consumo** | seed DEMO-01 (leituras SIMULADAS) | `energy` (degraus, sessões) | sessões «Consumo não identificado», proveniência visível | Browser | Sem coletor em runtime com FakeHome; localização/custo dependem da `main` ≥ #193 |
| **Notificação e votação** | pedido «De quem é esta conta?» (custo estimado ≥ limiar) | `billing/attributor` → `notifications` → voto (`confirmation_outcome`, D-32) | «É minha» decide logo; os outros veem «não fica a teu cargo»; orçamento passa a «Confirmado (meu)» | Browser (só «É minha») | «É de todos»/«Não sei»/«É de outra pessoa» e prazo 24 h só em testes |
| **Repartição financeira** | fatura finalizada | `billing/allocation.py` | quarto + zona comum + resíduo, soma exata | Browser + testes | Opção C (presença) não existe (#132) |
| **Orçamento** | valor mensal do morador | `billing/budgets.py` → notificações | «85 % utilizado»; aviso «Orçamento a 80 %» | Browser | Previsão mensal e tarifário não existem (#101) |
| **Fatura e recibos** | senhorio: período, total, fixo, kWh | `billing/bills.py`, `closing.py`, `explanation.py` | 120 € → 4 recibos que somam 120,00 € (também após reset); recibo explicado; aviso «Recibo disponível» | Browser | Contestação (#93) só em testes |
| **Reset e reprodução** | `make demo-reset` | `demo/cli.py`, `demo/web.py` | base de demo nova (cópia `.demo-web`), pedido «0 de 4 votos» regressa, contas mantidas | Browser | Nunca toca na base original `.demo-data` |
| **Ocupação e visitas** | passagens na porta (clip SIMULADO) + estados dos moradores | `presence/occupancy.py`, `GET /api/presence/occupancy` | número de pessoas dentro e de visitas; `uncertain` se a contagem não bate | Testes | Não visto no browser nesta data; sem câmara real; senhorio 403 |
| **Casa vazia (PRES-06)** | passagens na porta até 0, sem telemóveis em casa (clip SIMULADO) | `presence/occupancy.py` → `presence.occupancy_changed`, mesmo cálculo do cartão | `likely_empty` (e `occupied`/`uncertain` ao mudar), uma vez por mudança; sem rota nem UI nova | Testes | Câmara parada ou entrada perdida = `uncertain`; nunca arma nada (SAFE-02 #115 planeada); não visto no browser |

**Não demonstrável hoje:** assistente de IA (sem UI), escritas físicas (lâmpada/tomada), presença/câmara real, push/offline.
