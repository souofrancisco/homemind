# Progresso

A lista autoritativa de tarefas, prioridades, dependências e responsáveis é o **[GitHub Project «Conta Certa»](https://github.com/users/souofrancisco/projects/1)** e as suas issues; o resumo é a issue [#129](https://github.com/souofrancisco/homemind/issues/129). Esta página é um instantâneo de **2026-11-19**.

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

## Em desenvolvimento

Trabalho corrente segundo o handoff de 2026-11-19 (o Project manda):

- Interface do assistente de IA (#111) e voto → recibo na interface (#96).
- Validação do kit real, com planos B (#122).
- Contador agregado de visitas (#109) e modo sem câmara (#56).
- Cue RGB/texto de orçamento (#104); previsão mensal e tarifário (#101).
- Percurso único gravado, guião de 3 minutos e execuções ponta a ponta (#28, #123, #124).

## <span class="estado estado--plan">PLANEADO</span>

Issues abertas, por épico (29 abertas e 79 fechadas à data):

| Épico | Exemplos por fazer |
|---|---|
| Fundação (BASE) | Pedidos de P3 ao contrato (#157) |
| Casas (HOUSE) | Onboarding e substituição de moradores (#88); associação OIDC e papéis (#85) |
| Aplicação (APP) | Redesenho da navegação e identidade (#94); dashboard de potência (#97); push e offline (#99) |
| Alertas (ALERT) | Aparelho potencialmente esquecido (#103); Energy Insights (#55) |
| Assistente (AGENT) | Propostas de ações com confirmação (#112); regras em português (#113) |
| Privacidade (PRIV) | Auditoria de decisões financeiras e retenção (#120) |
| Demonstração (DEMO) | Hardware e planos B (#122); guião e perguntas do júri (#123); CI e testes ponta a ponta (#124); README e apresentação final (#29) |
| Piloto (PILOT) | Pesquisa com estudantes e senhorios (#125); produção multi-imóvel (#127); revisão jurídica/AIPD (#128) |

## <span class="estado estado--prop">PROPOSTA</span>

- Limite mensal de 5 kWh por aparelho antes de perguntar (implementado, por validar com a equipa).
- Prazos de retenção de presença e política de backups.
- Redistribuição de issues entre pessoas (depende de acordo da equipa).

!!! note "Esta página pode ficar desatualizada"
    Os números e os estados mudam no Project. Em caso de dúvida, a issue ganha sobre esta página.

*Fontes canónicas: `docs/functional-flows.md`, `docs/development/handoff.md`, `docs/development/roadmap.md`.*
