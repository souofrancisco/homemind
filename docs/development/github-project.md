# GitHub Project — Conta Certa · Desenvolvimento

**Project criado:** https://github.com/users/souofrancisco/projects/1/views/1  
**Repositório:** https://github.com/souofrancisco/homemind  
**Roadmap mestre:** [issue #129](https://github.com/souofrancisco/homemind/issues/129)  
**Mapa de issues:** [backlog.md](backlog.md) · **Equipa:** [team.md](team.md) · **Fases originais:** [roadmap.md](roadmap.md)

> Criado pelo responsável em 18/11/2026. A **configuração dos campos, das vistas e a importação dos itens do Project requerem acesso de escrita ao GitHub Projects**. A existência deste documento não confirma que esses passos tenham sido executados. Não declarar o Project organizado até os itens e as vistas serem verificados no GitHub.

## Fonte de verdade

- **GitHub Issues:** âmbito, critérios de aceitação, responsável, prioridades, dependências e estado aberto/fechado.
- **GitHub Project:** estado operacional da equipa, iteração, roadmap, fila de reviews e carga de trabalho.
- **Pull Requests:** implementação, testes e evidência de revisão. Uma issue aberta pode ter código integrado; não converter automaticamente isso em «Feito».
- **Documentação:** decisões estáveis e orientação; não manter uma segunda tabela de estado manual que contradiga o Project.

## Configuração proposta do Project

| Campo | Valores ou finalidade |
|---|---|
| Status (single select) | Backlog · Pronto · Em curso · Review · Bloqueado · Feito |
| Priority (single select) | P0 · P1 · P2 (alinhar com labels existentes) |
| Area (single select) | BASE · MCP · ENERGY · HOUSE · BILL · APP · ALERT · PRES · AGENT · SAFE · PRIV · DEMO · PILOT |
| Phase (single select) | F0 · F1 · F2 · F3 |
| Iteration | Ciclos de trabalho acordados pela equipa; não inventar datas |
| Assignees | Campo nativo GitHub — um responsável por entrega |
| Parent issue / Sub-issues | Hierarquia nativa; é diferente de dependência |
| Linked pull requests | Links nativos de issue/PR; PR com `Closes #N` apenas se cumprir a aceitação |

Criar as vistas **Roadmap**, **Kanban**, **Por responsável**, **MVP**, **Reviews e bloqueios**. Se a vista Roadmap exigir datas, usar apenas datas acordadas; não transformar fases F0–F3 em deadlines fictícios.

## Triage inicial fundamentado

Auditoria da pesquisa de issues em 18/11/2026: **54 abertas, 53 fechadas, 0 PRs abertos**. Estas contagens incluem épicos e histórico ObjectOS; não equivalem ao número de tarefas individuais pendentes.

| Grupo | Issues a rever primeiro | O que confirmar antes de marcar «Feito» |
|---|---|---|
| Demo end-to-end e browser (P5, com QA) | [DEMO-02 #28](https://github.com/souofrancisco/homemind/issues/28), [DEMO-01 #121](https://github.com/souofrancisco/homemind/issues/121), [DEMO-06 #124](https://github.com/souofrancisco/homemind/issues/124) | Login e percurso UI Ana/Bruno/Carla/Diogo, votação, fecho de 120 € e quatro recibos; falhas e repetição |
| Interface (P5/P3) | [APP-01 #94](https://github.com/souofrancisco/homemind/issues/94), [APP-02 #95](https://github.com/souofrancisco/homemind/issues/95), [APP-03 #96](https://github.com/souofrancisco/homemind/issues/96), [APP-05 #97](https://github.com/souofrancisco/homemind/issues/97), [APP-06 #98](https://github.com/souofrancisco/homemind/issues/98) | Backend/React existentes versus execução comprovada em browser e critérios de permissões |
| Identidade e políticas (P5/P4) | [HOUSE-02 #85](https://github.com/souofrancisco/homemind/issues/85), [HOUSE-04 #87](https://github.com/souofrancisco/homemind/issues/87), [BILL-02 #90](https://github.com/souofrancisco/homemind/issues/90) | Convites reais protegidos, políticas versionadas e sem duplicar o atribuidor |
| Energia (P1) | [ENERGY-04 #82](https://github.com/souofrancisco/homemind/issues/82), [ENERGY-05 #83](https://github.com/souofrancisco/homemind/issues/83), [DEMO-03 #122](https://github.com/souofrancisco/homemind/issues/122) | Evidência de medição/localização, limites de uma tomada e confirmação física autorizada |
| Assistente (P3) | [AGENT-01 #110](https://github.com/souofrancisco/homemind/issues/110), [AGENT-02 #111](https://github.com/souofrancisco/homemind/issues/111) | Ferramentas read-only, isolamento de dados e UI real; não inventar resultados |
| Financeiro (P4) | [BILL-05 #52](https://github.com/souofrancisco/homemind/issues/52), [BILL-02 #90](https://github.com/souofrancisco/homemind/issues/90) | Rastreabilidade e regras em casos incertos |
| Apresentação (P5, delegável após acordo) | [DEMO-04 #123](https://github.com/souofrancisco/homemind/issues/123), [DEMO-05 #29](https://github.com/souofrancisco/homemind/issues/29) | Guião de 3 minutos, teste completo e documentação atualizada |
| Pós-MVP | PILOT, AWAY, automações avançadas e extras | Não ocupar a fila `Pronto` enquanto a demo crítica estiver por validar |

**Redistribuição:** as atribuições atuais mantêm-se até decisão da equipa. Na reunião seguinte, separar QA do código P5 e propor colaboração de P2 nos testes do browser, se houver capacidade. Não atribuir tarefas a membros sem lhes comunicar.

## Regras de fluxo com IA

1. **Triagem:** antes de implementar, comparar issue com `main`, histórico de PRs, comentários e testes. Classificar: totalmente implementado e validado; implementado sem validação; parcial; bloqueado; não iniciado; pós-MVP.
2. **Pronto:** critérios objetivos, ficheiros/contratos relevantes, um responsável, dependências concluídas. Não colocar trabalho sem especificação em Pronto.
3. **Em curso:** uma issue executável por pessoa de cada vez. Claude/Codex podem usar **worktrees separadas**, nunca o mesmo checkout ou ficheiros partilhados em paralelo.
4. **Review:** abrir PR ligado à issue; indicar testes locais realmente executados, limitações, autor/revisor humano e como testar. Rever segurança, permissões, valores financeiros e contratos entre features.
5. **Feito:** validar comportamento exigido; só depois fechar issue. Merge e testes de backend não substituem validação exigida no browser ou hardware.
6. **Bloqueado:** indicar o que falta, dono da dependência e issue/PR correspondente; usar `blocked by` nativo quando possível.
7. **Áreas partilhadas:** respeitar `CLAUDE.md`/`AGENTS.md`, sobretudo `core/`, `contracts/`, frontend e regras de import entre features.
8. **CI:** a GitHub Actions CI encontra-se desativada por decisão explícita. Não reativar. Registar validações locais; não declarar CI verde.
9. **Responsabilidade humana:** IA propõe e executa alterações isoladas; um membro da equipa revê antes do merge. Sem merges automáticos nem ciclos ilimitados de agentes.

## Passos de ativação no GitHub

1. Abrir [o Project #1](https://github.com/users/souofrancisco/projects/1/views/1).
2. Associar `homemind` ao Project e importar issues/épicos existentes, **sem duplicar**.
3. Criar campos, vistas e filtros acima.
4. Verificar relações nativas de sub-issues para os 13 épicos do [backlog](backlog.md); não confundir com `blocked by`.
5. Para cada issue aberta, confirmar evidência, atualizar status e atribuições; encerrar apenas as validadas.
6. Antes de anunciar conclusão, verificar que cada pessoa vê a sua fila de trabalho e que o Project não omite tarefas abertas de MVP.
