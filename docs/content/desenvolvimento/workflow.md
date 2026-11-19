# Workflow de desenvolvimento

**issue → investigação → plano → implementação isolada → testes → revisão independente → PR → validação humana → merge**

1. **Issue.** Uma tarefa = uma issue do [GitHub Project](https://github.com/users/souofrancisco/projects/1) em *Pronto*, com a pessoa como responsável e sem *blocked by* abertos.
2. **Implementação isolada.** `make worktree b=feat/<n>-<nome>`; um agente por worktree, nunca o de outro.
3. **Âmbito.** Só o pedido, no estilo existente; sem dependências, abstrações ou funcionalidades extra. Atualizar o documento correspondente no mesmo PR.
4. **Testes.** `make check`; `make demo-up` e o browser para a interface.
5. **Revisão independente.** Outra pessoa ou agente lê o *diff*; no máximo duas rondas.
6. **PR pequeno** para `main` com: o que mudou, testes realmente corridos, limitações. Sem push direto para `main`; merge só por uma pessoa.

## Agentes de IA

Claude Code coordena (âmbito, integração, revisão do *diff*); Codex recebe trabalho independente e delimitado. Antes de delegar, confirma-se que não há ficheiros em comum com outro agente. Os relatórios dos agentes são dados, não prova.

Regras que os agentes não saltam: sem escritas físicas sem autorização explícita nessa tarefa; sem segredos em Git ou logs; vídeo só local; senhorio nunca vê presença; simulado nunca apresentado como real.

## Propriedade por módulo

Mudar propriedade ou tocar no módulo de outra pessoa exige acordo. Ver [Equipa](../equipa/index.md).

*Fontes canónicas: `CLAUDE.md`, `docs/ai-workflow.md`.*
