# Frontend — Conta Certa

Regras gerais em [`../../CLAUDE.md`](../../CLAUDE.md). A aplicação React/Mantine/Capacitor é a interface da Conta Certa para moradores, senhorios e operadores. O frontend **IMPLEMENTADO** organiza a navegação em Hoje, Contas, Casa e Assistente para moradores; Hoje, Contas e Casa para senhorios; Casa e Diagnóstico para operadores. O sino abre Notificações e o menu do perfil dá acesso a Definições, tema, sessão e seleção de associação. `/consumo`, `/orcamento` e `/aparelhos` redirecionam para os destinos atuais; Notificações e Definições continuam como rotas fora da navegação.

## Estrutura

| Pasta | Regra |
|---|---|
| `src/app/` | `App`, `routes.tsx` e providers de autenticação e casa (`AuthProvider`, `HouseholdProvider`) |
| `src/pages/` | Páginas ligadas à navegação e compostas com componentes e serviços |
| `src/components/<área>/` | Apresentação por área (`billing`, `layout`, `notifications`, `presence`) |
| `src/hooks/` | Hooks de interface, como `usePolling` |
| `src/services/` | `api/client.ts` (HTTP + token), `auth/` (OIDC) e serviços por domínio (`appliances`, `billing`, `diagnostics`, `energy`, `households`, `notifications`, `presence`, `agent`) |
| `src/shared/api/` | OpenAPI e tipos gerados; não editar manualmente |

## Convenções

- **Mantine primeiro:** componentes, tema e notificações do Mantine; sem CSS próprio quando existe um componente. Ícones de `@tabler/icons-react`.
- **API:** todas as chamadas passam por `services/api/client.ts` (`request`), que junta o Bearer e trata o 401. Nunca `fetch` direto nos componentes. Tipos da API vêm do OpenAPI gerado.
- **Estados visíveis:** apresentar loading, erro e vazio de forma clara. Indicar a proveniência `measured`, `estimated`, `inferred` ou `simulated` sempre que aplicável; não apresentar simulações como dados reais.
- **Segurança:** o frontend nunca fala com o MCP nem envia frames para fora. Tokens só no armazenamento do `oidc-client-ts` (Keystore no Android).
- **Acessibilidade:** legível à distância, com contraste e foco visíveis; layout funcional em telemóvel (Capacitor) e desktop.

## Verificação

`npm run gen:api`, `npm run lint` e `npm run build` verificam geração dos tipos, ESLint e compilação/build. A validação manual da interface segue o [`guia de validação`](../../docs/development/guia-validacao-manual.md).
