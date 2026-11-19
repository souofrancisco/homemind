# Equipa

Cinco pessoas, cinco áreas com o mínimo de sobreposição. Identificadas pelo utilizador de GitHub.

| | Pessoa (GitHub) | Área |
|---|---|---|
| P1 | `brunovieira88` | MCP, dispositivos, energia e assinaturas elétricas |
| P2 | `1Mii` | Visão computacional e presença |
| P3 | `RafaelMat0s-Dev` | Assistente de IA, notificações e interação na aplicação |
| P4 | `Amorim3000` | Faturação, repartição, orçamentos e alertas |
| P5 | `souofrancisco` | Arquitetura, integração, frontend e demonstração |

## Organização

- **Uma issue → um branch → um worktree → um PR.** Prioridades P0 (essencial), P1 (aprofundamento), P2 (extensão); fases F0 (fundação), F1 (vertical energia → notificação → fatura), F2 (presença e demo sólida), F3 (opcional).
- **Propriedade por módulo:** cada pessoa trabalha na sua pasta `features/<módulo>/`. Uma feature não importa outra.
- **Ficheiros partilhados** (`core/`, `contracts/`, `Makefile`, Compose, `.github/`) têm revisão obrigatória de P5.
- **Contratos primeiro:** ninguém implementa um módulo antes de os contratos dele estarem acordados.
- Mudar propriedade ou tocar no módulo de outra pessoa exige acordo da equipa.

As tarefas, prioridades e dependências vivem no [GitHub Project](https://github.com/users/souofrancisco/projects/1), que é a lista autoritativa.

*Fonte canónica: `docs/development/team.md`.*
