# Testes

## Comandos

| Comando | O que faz |
|---|---|
| `make check` | Lint (ruff + eslint) + `pytest` + contrato OpenAPI→TS + build + validação do Compose. Tem de passar antes de pedir revisão |
| `make test` | Só `pytest` |
| `make smoke` | Stack Docker isolada; obrigatório quando se toca em Docker, arranque ou proxy |
| `make contracts` | Regenera os tipos TypeScript a partir do OpenAPI |

## Princípios

1. **Lógica pura com fakes e relógio simulado.** Nunca depender de hardware, rede, LLM ou MCP real em `pytest`.
2. **Uma correção de bug traz um teste que falha sem ela.**
3. O hardware valida-se à mão pelo guia de validação; **nunca** se marca PASS o que não foi executado.
4. Testes ao lado da feature (`features/<nome>/tests/`).
5. Sem frames reais, segredos nem identificadores de dispositivos nos testes, logs ou fixtures.

## Autorização

Cada rota nova leva um teste papel × rota, incluindo isolamento entre casas e DTOs sem campos privados.

## Frontend

Não há testes unitários de frontend: a verificação é `eslint`, `tsc -b` e `vite build` no `make check`, mais validação manual no browser.

## Documentação

O build da documentação (`mkdocs build --strict`) corre num workflow próprio; ver [Este website](website.md).

!!! warning "CI geral"
    O workflow `CI` (que corre `make check`) está **desativado** no repositório. A verificação do código é `make check` local.

*Fonte canónica: `docs/development/testing.md`.*
