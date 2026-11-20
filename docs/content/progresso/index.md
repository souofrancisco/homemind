# Progresso

A lista autoritativa de tarefas, prioridades, dependências e responsáveis é o **[GitHub Project «Conta Certa»](https://github.com/users/souofrancisco/projects/1)** e as suas issues; o resumo é a issue [#129](https://github.com/souofrancisco/homemind/issues/129). Esta página é um instantâneo de **2026-11-20**.

## <span class="estado estado--ok">IMPLEMENTADO</span>

Validado no browser ou por testes, sempre com dados simulados ([detalhe](../demo/verificado.md)):

- Login Authentik (OIDC) com papéis e isolamento de dados entre eles.
- Casa, quartos, zonas comuns; consumo por tomada com proveniência.
- «De quem é esta conta?» com votação dos moradores.
- Fatura do senhorio, repartição quarto/comum/resíduo, recibos que somam a fatura, recibo explicado.
- Orçamento mensal com avisos a 50/80/100 %.
- Consentimento por fonte de presença, retenção e exportação.
- Alarme simulado com confirmação; regras da casa votadas (motor simulado).
- Estimativa da lâmpada; consumo da tomada offline.
- Assistente de IA na aplicação, com propostas de ação confirmadas (#111, #112; só testes).
- Previsão do fim do mês e tarifário (#101); indicador RGB de orçamento (#104); contagem de visitas (#109); modo sem câmara (#56); voto na interface (#96); navegação redesenhada (#94).
- «O que é este aparelho?» para consumos desconhecidos (ENERGY-04; só testes).

## Em desenvolvimento

Issues abertas com trabalho corrente (o Project manda):

- Validação do kit real, com planos B (#122).
- Guião de 3 minutos e execuções ponta a ponta (#123, #124); README e apresentação final (#29).

## <span class="estado estado--plan">PLANEADO</span>

Issues abertas, por épico (24 abertas e 84 fechadas à data; as de «Em desenvolvimento» repetem-se na linha da Demonstração):

| Épico | Exemplos por fazer |
|---|---|
| Fundação (BASE) | Pedidos de P3 ao contrato (#157) |
| Casas (HOUSE) | Onboarding e substituição de moradores (#88); associação OIDC e papéis (#85) |
| Aplicação (APP) | Dashboard de potência (#97); push e offline (#99) |
| Alertas (ALERT) | Aparelho potencialmente esquecido (#103); Energy Insights (#55) |
| Assistente (AGENT) | Regras em português (#113) |
| Privacidade (PRIV) | Auditoria de decisões financeiras e retenção (#120) |
| Demonstração (DEMO) | Hardware e planos B (#122); guião e perguntas do júri (#123); CI e testes ponta a ponta (#124); README e apresentação final (#29) |
| Piloto (PILOT) | Pesquisa com estudantes e senhorios (#125); produção multi-imóvel (#127); revisão jurídica/AIPD (#128) |

## <span class="estado estado--prop">PROPOSTA</span>

- Limite mensal de 5 kWh por aparelho antes de perguntar (implementado, por validar com a equipa).
- Regra de votação das regras da casa (D-35; implementada, por rever por P3 e P5).
- Prazos de retenção de presença e política de backups.
- Redistribuição de issues entre pessoas (depende de acordo da equipa).

!!! note "Esta página pode ficar desatualizada"
    Os números e os estados mudam no Project. Em caso de dúvida, a issue ganha sobre esta página.

*Fontes canónicas: `docs/functional-flows.md`, `docs/development/handoff.md`, `docs/development/roadmap.md`.*
