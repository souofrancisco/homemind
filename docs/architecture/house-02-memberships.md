# HOUSE-02 (#85) — Identidade, associação e memberships

Estado: implementado na branch feat/house-02-memberships; revisão e testes CI necessários antes do merge.
Dono: P5. F0 mantém-se: Authentik com OIDC/PKCE, modelos de domínio de
contracts/household.py, SQLite, core/access.py (matriz única PERMISSIONS).

## Auditoria

**Existia (main F0):** validação JWT RS256/JWKS, issuer/audience, CurrentUser,
resolver access por sub, consultas de casas/quartos/membros e /api/me/context,
PATCH de presence_opt_in próprio, índices parciais de membership, datas no fuso
da casa, seed de demonstração e testes de isolamento.

**Faltava:** fluxo transacional e auditável de convite, associação de um sub ao
Resident, ativação, revogação REST, criação REST de quartos, controlo de utilização
única e expiração, timestamp UTC real em insert_resident, mesma primitiva de
autenticação para futuros WS e filtragem temporal dos membros listados a inquilinos.

## Comparação de arquitetura

Notas 1 (pior) a 5 (melhor). Pontuação ponderada calculada por soma
de peso x nota / 5.

| Critério | Peso | A Administrada | B Convite seguro | C Pedido/aprovação |
|---|---:|---:|---:|---:|
| Segurança e isolamento | 25 | 4 | 5 | 4 |
| UX | 15 | 2 | 5 | 4 |
| Simplicidade | 15 | 5 | 3 | 3 |
| Integração F0 | 15 | 5 | 5 | 4 |
| Testabilidade | 10 | 5 | 5 | 4 |
| Baixo risco de colisões | 10 | 5 | 4 | 3 |
| Múltiplas casas | 5 | 4 | 5 | 5 |
| Baixa manutenção | 5 | 5 | 4 | 3 |
| **Total / 100** | **100** | **85** | **88** | **74** |

**Decisão: B, restrita a convites de inquilinos por senhorios existentes.**
A é a solução mais fácil, mas exige ao senhorio conhecer o sub interno do
destinatário ou uma gestão administrativa manual; C introduz pedidos públicos,
aprovações e descoberta de imóveis não necessários ao MVP. B reutiliza o estado
invited e o OIDC existente, sem novas dependências, trabalhadores ou email
automático. É um convite privado distribuído pelo senhorio, não um diretório
de casas. Não se adicionou auto-registo de senhorio/operador nem autoelevação.
O primeiro senhorio/operador e a casa são provisionados por ferramenta
administrativa/seed **fora do REST público**, com controlo operacional; uma
provisão real de produção (sem seed demo) é um passo operacional pendente.

Referências oficiais consultadas:
- FastAPI — dependencies: https://fastapi.tiangolo.com/reference/dependencies/
- Authentik — provider OIDC e scopes: https://docs.goauthentik.io/add-secure-apps/providers/oauth2/
- Authentik — verificação efetiva de email: https://docs.goauthentik.io/add-secure-apps/providers/oauth2/verify-email-address/
- OWASP — multi-tenant security: https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html
- OWASP — authorization: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html

## Pré-condição de segurança: email_verified

O token de acesso assinado e válido tem de incluir email e
email_verified=true para aceitar um convite. O backend **não aceita**
email_verified omitido ou false; não deriva este valor do domínio do
email nem confia em parâmetros enviados pelo cliente. Desde Authentik
2025.10, o mapping padrão de email devolve false, por não provar que o
endereço é verificado. Por isso o administrador deve implementar o fluxo
de verificação de email recomendado na documentação oficial e substituir
o mapping do scope email pelo que devolve o estado realmente verificado.
NÃO configurar email_verified=true incondicionalmente.

**Gate de integração:** confirmar que o access token (não apenas o ID
token) inclui email e email_verified=true depois de email validado.
Sem esta configuração, os convites são emitidos mas nenhuma aceitação
ocorre; é uma falha segura e intencional, não um modo demo que contorna
a validação. A UI de verificação/onboarding é HOUSE-05.

## Endpoints

Todos os endpoints usam Bearer do Authentik via CurrentUser. O corpo
de comandos é extra=forbid. A estrutura de erro é sempre
{"error":{"code":"...","message":"..."}}.

| Método | Caminho | Quem | Resposta |
|---|---|---|---|
| GET | /api/me/context | autenticado | MeContext, só memberships efetivas e residente próprio |
| GET | /api/households/{household_id} | membro efetivo | HouseholdView |
| GET | /api/households/{household_id}/rooms | membro com leitura room | RoomView[] |
| GET | /api/households/{household_id}/members | tenant/landlord | MemberView[]; tenant só membros na data local |
| PATCH | /api/households/{household_id}/memberships/{membership_id} | tenant próprio | MembershipSelfView; apenas presence_opt_in |
| POST | /api/households/{household_id}/rooms | landlord | 201 RoomView |
| POST | /api/households/{household_id}/invitations | landlord | 201 {invitation_id,code,expires_at} |
| POST | /api/invitations/accept | utilizador OIDC com email verificado | 200 MembershipSelfView |
| POST | /api/households/{household_id}/memberships/{membership_id}/revoke | landlord, apenas tenant | 200 MemberView terminado |

### Exemplo (corpos)

POST /api/households/{household_id}/rooms

    {"name":"Quarto 5","kind":"bedroom","included_wh":30000}

POST /api/households/{household_id}/invitations

    {"display_name":"Maria","email":"maria@example.org",
     "room_id":"UUID-do-quarto","starts_on":"2026-12-01","ends_on":null}

POST /api/invitations/accept

    {"code":"segredo-entregue-uma-vez-pelo-senhorio"}

Os UUID são ilustrativos; obter o room_id da rota de quartos. Não incluir
token em path, query, analytics, logs, notificações globais ou eventos;
enviar no corpo HTTPS. O código de convite de uso único só volta ao senhorio uma
vez. O backend não faz delivery de emails; HOUSE-05 implementa a UI.

## Estados e transições

- landlord cria convite -> novo Resident reservado sem auth_subject ->
  Membership(invited) e membership_invitation(pending). Role sempre tenant.
- tenant autentica com OIDC, apresenta token, mesmo email verificado,
  token válido, não revogado nem usado -> liga sub ao Resident ou reutiliza
  o Resident global já associado ao sub -> Membership(active) ->
  invitation.redeemed_at preenchido. Tudo numa transação BEGIN IMMEDIATE.
- Uma membership active com starts_on no futuro continua sem grants;
  termina o acesso ao passar ends_on no fuso da casa.
- landlord revoga tenant invited ou active -> Membership(ended) com
  ends_on e convite pendente revoked_at. Sem hard delete ou reatribuição
  de contratos antigos. Para trocar de quarto/morador, terminar o
  contrato anterior e criar um novo: papéis e datas são imutáveis.
- role landlord/operator não pode ser criado nem revogado por estas rotas.
  Provisionamento privilegiado é ação administrativa fora do REST.

Um convite tem 72 horas de duração. O token é aleatório com 256 bits,
guardado apenas com SHA-256. O alvo é o email normalizado, persistido
internamente: é dado pessoal, sujeito a política de retenção (PRIV-01).
Não há cleanup automático de reservas expiradas; a tabela pode ser
expurgada por um processo de retenção posterior sem apagar memberships
contratuais. A revogação é imediata pelo estado ended, mesmo se a data
ends_on é inclusiva para cálculo contabilístico. Os timestamps reais
são UTC e as datas contratuais são locais à casa.

### Erros

- 401: sem Bearer/assinatura/audience/issuer inválidos.
- 403 forbidden_role: membro da casa sem papel; alterações indevidas.
- 403 verified_email_required: email de conta não verificado.
- 404 household_not_found: casa inexistente ou sem membership efetiva,
  mesmos corpo/código; id de membership fora da casa também ocultado.
- 404 room_not_found: quarto fora da casa/inexistente na criação.
- 404 invitation_not_found: token inexistente, vencido, revogado ou email
  diferente, sem revelar o destinatário.
- 409 invitation_used: token já resgatado.
- 409 membership_conflict: conflito de ocupação, duplicado ou contrato
  terminado; nunca expor mensagem de SQLite.
- 400 invalid_request: parâmetros extra ou tipos/datas inválidos.

## Integração para P1/P2/P3/P4

Código ilustrativo para cada router de domínio, usando F0 e o mesmo
HouseholdAccess. Não ler resident_id, household_id de um DTO de origem
externa como prova de autorização. Consultas devem manter
WHERE household_id=? e filtrar por grant/room_id/resident_id.

    from typing import Annotated
    from fastapi import Depends
    from homemind.core.access import HouseholdAccess, Resource, Operation, require_access

    ReadEnergy = Annotated[HouseholdAccess, Depends(require_access(Resource.energy))]
    WritePresence = Annotated[
        HouseholdAccess, Depends(require_access(Resource.presence, Operation.write))
    ]

    # P1: energy -> grant aggregate/own/diagnostic decide o DTO e o filtro.
    # P2: presence -> grant own só pode escrever access.resident_id.
    # P3: notification -> filtrar recipient_resident_id por access.resident_id.
    # P4: billing -> landlord agregado, tenant apenas access.resident_id.

Futuro WS: receber um token no primeiro frame, nunca na query string;
auth.validate_access_token(token) verifica o mesmo JWKS/claims de REST.
Depois, em cada inscrição/ação com household_id, chamar
await resolve_access(db, user.sub, household_id, resource, op, clock()).
Revalidar em cada ação e na publicação de cada recurso protegido,
porque a membership pode ter sido revogada. Não reutilizar um grant
anterior à revogação como sessão autorizada indefinidamente.
O WS legado ObjectOS ainda não usa este modelo: integrar quando o
módulo WS de Conta Certa existir (HOUSE-05/APP/PRIV). **Não afirmar que
todo o WS existente está protegido por estas guardas.**

## Limites intencionais

Não foram alterados os modelos F0 de Household/Room/Resident/Membership,
PERMISSIONS ou as migrações 0001/0002. A migração 0003 é aditiva.
Não há UI de onboarding, envio de email, motor de aprovação, recuperação
de convites por email, gestão de senhoria nem autoatribuição de operador.
Aceitação exige que o provedor forneça claims verificados.
Permissões aplicadas aos módulos P1–P4 dependem de cada rota usar
require_access e filtrar os DTOs; não são concedidas automaticamente
por ocultação da UI.

## Verificação

Em app/backend: uv run ruff check ., uv run ruff format --check .,
uv run pytest -q. Na raiz: make check (inclui build e Docker Compose).
Teste de aceitação: duas casas, dois senhorios, convites/expiração,
token repetido, email errado/não verificado, troca de morador, múltiplas
memberships do mesmo sub, contrato futuro/expirado, revogação e 401/403/404.
Validar claims OIDC reais e revogação em sessão real antes de apresentar
o fluxo como pronto para piloto.
