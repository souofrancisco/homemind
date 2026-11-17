# Módulo `households` — casas, quartos, moradores e persistência

**Dono: P5 (souofrancisco).** **IMPLEMENTADO (F0 + HOUSE-02 nesta branch): leituras REST, persistência, guardas, criação de quartos, convites tenant e revogação.** Entidades: [data-model.md](../architecture/data-model.md). Contratos: [contracts.md](../architecture/contracts.md).

## Responsabilidade

Fonte de verdade de **quem vive onde e com que papel**: `Household`, `Room`, `Resident`, `Membership`, e das **permissões** que todos os outros módulos aplicam. Também é dono da persistência partilhada (`core/db.py`, migrações, `domain_event`) e do barramento (`core/events.py`).

## Recebe / produz

| Recebe | Produz |
|---|---|
| Pedidos REST da aplicação (criar casa, quartos, convites) | `Household`, `Room`, `Resident`, `Membership` |
| Identidade do Authentik (`sub`) | Resolução `utilizador → memberships → papel` (dependência FastAPI para todos os routers) |
| — | Eventos: `households.membership_changed` (entrada/saída de morador, mudança de quarto) |

## Regras

- O vínculo pessoa–quarto vem do contrato de arrendamento e é **introduzido pelo senhorio**; o sistema nunca o adivinha (PDF §10.3).
- Convite: senhorio cria uma membership `invited` para um quarto e email de destino; o token secreto é entregue uma única vez, expira em 72 h e só é aceite com OIDC e email realmente verificado. Ver [HOUSE-02](../architecture/house-02-memberships.md). A UI do link pertence a HOUSE-05.
- Papéis em `Membership.role`. Autorização: `require_access(Resource, Operation)` em `core/access.py` (matriz `PERMISSIONS`): `403 forbidden_role` para membros sem papel, `404 household_not_found` para não-membros. Decisão pendente P-02 (papéis na base de dados vs grupos do Authentik); recomendação: base de dados, para não depender da configuração do Authentik.
- DTOs por papel: o senhorio **nunca** recebe presença nem aparelhos individuais (RP-01).
- `presence_opt_in` é editado só pelo próprio inquilino.
- Saída a meio do mês: a membership fecha com `ends_on`; a fatura usa as datas.

## Persistência (SQLite)

Esquema versionado em ficheiros SQL numerados; chaves estrangeiras ligadas; modo WAL. Acesso e testes com base em memória. Biblioteca: `sqlite3` da stdlib (P-05 resolvido, D-25/D-29); `core/db.py`, `core/migrations/`. Dados de demonstração por *seed* determinístico, sempre `source_kind=demo`.

## Ficheiros previstos

`features/households/{router,repo,membership_flow,tests}`; `core/db.py`, `core/events.py`, `core/migrations/*.sql`; Authentik/JWT mantém-se em `features/auth/service.py`. O provisionamento do primeiro senhorio é administrativo, não é um endpoint público.

## Dependências

P1, P2, P3, P4 dependem das dependências de autorização e do barramento — **é o primeiro entregável da equipa** (ver [development/roadmap.md](../development/roadmap.md)).

## Critérios de aceitação

- Criar uma casa de demonstração com 4 quartos e 4 moradores por *seed* num único comando.
- Um inquilino não consegue obter dados de outro inquilino; um senhorio obtém `403 forbidden_role` em qualquer rota de presença ou aparelhos.
- `Σ` de moradores ativos numa data = membros no período (teste de saída a meio do mês).
- Barramento: `publish` e `subscribe` com handlers idempotentes e `domain_event` gravado.

## Testes

Autorização por papel (tabela de rotas × papéis); migrações aplicam-se do zero; barramento com handler que falha não afeta os outros; *seed* repetível.

## Interface HOUSE-02

O backend disponibiliza `POST /api/households/{household_id}/rooms`, `POST /api/households/{household_id}/invitations`, `POST /api/invitations/accept` e `POST /api/households/{household_id}/memberships/{membership_id}/revoke`. O contrato das respostas mantém `RoomView`, `MemberView` e `MembershipSelfView`. Email, `auth_subject` e hash do token não são publicados nos DTOs. [Estados, erros, matriz ponderada e integrações](../architecture/house-02-memberships.md).

**Pré-condição real:** Authentik tem de disponibilizar `email_verified=true` apenas após verificar efetivamente o endereço; o mapping padrão não basta. HOUSE-05 implementa a experiência visual. Os eventos de alteração de membership são trabalho de integração futura, não reivindicados por este PR.
