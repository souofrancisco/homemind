# Funcionalidades verificadas

Só fluxos **comprovados**. Estados usados:

- **Browser:** percorrido com Playwright/Chromium contra a demonstração (SIMULADA).
- **Testes:** coberto por `pytest`, não visto no browser.
- **Hardware:** nunca validado. **Nenhum fluxo foi validado com hardware real.**

| Fluxo | Estado | Limitações |
|---|---|---|
| Autenticação e casa (Authentik OIDC + PKCE) | Browser | Contas só no Authentik local; verificação de email real bloqueada (#85) |
| Permissões por papel | Browser + HTTP | Matriz testada por amostra, não exaustiva |
| Consumo por tomada | Browser | Sem coletor em runtime com FakeHome |
| Notificação e votação «De quem é esta conta?» | Browser (só «É minha») | «Escolher responsável(eis)», «Não sei» e prazo de 24 h só em testes |
| Repartição financeira | Browser + testes | Opção C (presença) não existe |
| Orçamento a 50/80/100 % | Browser | Previsão do fim do mês e tarifário só em testes |
| Fatura e recibos | Browser | Contestação só em testes |
| Reset e reprodução da demo | Browser | Nunca toca na base original |
| Controlos manuais sem câmara (lâmpada, SIMULADO) | Browser (2026-11-18) | Sem leitor de ecrã nem contraste medidos; nenhuma escrita física real |
| Consentimento por fonte de presença, retenção e exportação | Browser (2026-11-19) + testes | **Pistas injetadas à mão; nunca com Wi-Fi, aparelho ou telemóvel reais**; prazos PROPOSTA; sem revisão jurídica |
| Regras da casa votadas | Testes + browser com emissor OIDC falso e Authentik real (2026-11-19) | Motor SIMULADO; sem executor físico |
| Alarme simulado (armar/desarmar com confirmação) | Browser (2026-11-19) | Só simulado; a leitura MCP real é só de leitura e o estado físico não foi confirmado |
| Consumo da tomada offline e estimativa da lâmpada | Testes | SIMULADO; sem hardware |
| Assistente de IA na aplicação | Testes | LLM desligado por omissão; dados simulados; não visto no browser |
| «O que é este aparelho?» (aparelho desconhecido) | Testes | Não visto no browser; sem hardware |
| Ocupação e visitas; casa vazia | Testes | Sem câmara real |
| Limite mensal de 5 kWh antes de perguntar | Testes | PROPOSTA por validar com a equipa |

**Não demonstrável hoje:** escritas físicas reais, presença e câmara reais, push e offline.

## Isolamento por papel

Verificado por HTTP com o token de cada conta (esperado = obtido):

- Sem token → 401.
- **Senhorio:** 403 em recibo pessoal, consumo detalhado, presença, aparelhos e orçamento pessoal; 200 no resumo da fatura.
- **Morador:** 403 em pré-visualizar, finalizar e resumo de faturas do senhorio, e em dispositivos.
- **Operador:** 403 em faturas, consumo e presença; 200 em dispositivos.
- Casa inexistente → 404.

## Recibos que somam a fatura

Fatura de 120 € repartida em quatro recibos: 30,00 + 29,99 + 30,00 + 30,01 = **120,00 €** numa execução, e 29,99 + 29,99 + 30,01 + 30,01 = **120,00 €** após `make demo-reset`. O fecho reconcilia sempre a 100 % da fatura.

## Evidência e datas

A evidência (capturas de ecrã e notas) está em `docs/evidence/` no repositório e **não é publicada neste website**. Validações a 2026-11-18 e 2026-11-19.

*Fonte canónica: `docs/functional-flows.md`.*
