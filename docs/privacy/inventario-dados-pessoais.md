# Inventário de dados pessoais e política de backups (PRIV-03 #51)

> **Estado: PROPOSTA técnica, escrita pela equipa de desenvolvimento (P2) sem revisão de DPO nem de jurista.** Não afirma conformidade RGPD nem com a CNPD. Os prazos aqui são os que o código tem por omissão ou propostas; **continuam por decidir** (P-08, P-20, P-24, P-25). Dados reais de pessoas: não usar até haver decisão (P-24). Decisão D-37 em [decisions.md](../decisions.md).

Fonte de verdade das tabelas: `app/backend/src/homemind/core/migrations/`. Base única SQLite; o vídeo nunca é gravado nem enviado (só se analisa a soleira da porta, em memória, e só saem eventos «entrou»/«saiu»).

## Dados pessoais por categoria

| Categoria | Onde (tabela ou evento) | Quem vê | Prazo hoje | Eliminação / saída |
|---|---|---|---|---|
| Identidade | `resident` (`display_name`, `auth_subject` = `sub` do Authentik), `membership` (papel, quarto, datas), `membership_invitation` (email-alvo, hash do token) | O próprio; colegas veem o nome (`MemberView`); o senhorio vê os membros da casa | Sem prazo (necessária à conta) | Anonimização de ex-moradores EXISTE mas está **desligada** (`RETENTION_ANONYMIZE_AFTER_DAYS`, PRIV-04) até haver prazos |
| Consentimentos de presença | `membership.presence_opt_in` (global); `presence_source_consent` (estado por fonte); `presence_consent_log` (registo **só de acrescentar**: quem, o quê, quando, versão do texto, motivo) | Só o próprio (e exportação própria) | **Registo sem prazo definido (PROPOSTA a decidir com o DPO)**: não contém presença, só consentimentos; serve de prova | O estado por fonte apaga-se/desliga-se; o registo **não se apaga** (é a prova do consentimento) |
| Presença individual (pistas) | `domain_event` `presence.cue_recorded` (Wi-Fi, aparelho, manual), `presence.changed`, `presence.confirmation_needed`; `presence_confirmation` | Só o próprio | Brutos até `PRESENCE_RETENTION_DAYS` (30, **PROPOSTA**), depois agregados | Desligar **uma fonte** apaga as pistas dessa fonte e as mudanças que a citam; desligar o opt-in global ou sair da casa apaga tudo o que é do morador |
| Presença: estado e telemóveis | `presence_state`; `presence_device` (`match_key` = HMAC do MAC, **nunca o MAC**) | Só o próprio | Em vigor | Idem; revogar a fonte Wi-Fi ou o telemóvel apaga o `match_key` |
| Presença: agregados | `presence_daily` (segundos por estado e pistas por fonte, sem horários), `presence_door_daily` (anónimo) | Só o próprio / ninguém (porta) | Sem prazo definido (**PROPOSTA a decidir**) | Apagado com o morador; desligar uma fonte zera só a contagem dessa fonte (as durações agregadas não se decompõem por fonte e não têm horários) |
| Presença: auditoria | `presence_retention_log` (ação, casa, morador, motivo, contagens) | Ninguém por API | Sem prazo definido | Só contagens, nunca conteúdo |
| Cópia da faturação | `billing_presence_state`, `billing_occupancy` | Só a faturação (nunca API nem senhorio) | 40 dias (`RETENTION`) e logo ao revogar uma fonte (`presence.source_revoked`) ou o opt-in | Idem |
| Consumo e atribuição | `domain_event` `energy.*`, `billing.*`; `billing_consumption`, `billing_attribution`, `billing_confirmation`, `billing_allocation*`, `billing_contestation`, `billing_budget`, aparelhos (`appliance*`, dono declarado) | O próprio os seus; o senhorio só totais por quarto | Telemetria em bruto 90 dias (`RETENTION_TELEMETRY_DAYS`, PROPOSTA); evidência financeira **sem expurgo** (trigger da base) | Nunca se apaga o que explica uma cobrança; prazo legal por fixar (P-08) |
| Notificações | `notification`, `notification_read`, `notification_preferences` | O destinatário (e as da casa, os moradores) | Sem expurgo (PLANEADO) | **Não tocadas** pela eliminação de presença (módulo de P3): uma pergunta «estás em casa?» já enviada fica |
| Assistente | `agent_message`, `agent_action*` | O próprio | Mensagens: 50 por morador e 30 dias (`AGENT_HISTORY_*`, P-25) | Corte ao gravar; nunca vai ao LLM |
| Regras da casa e regras individuais (D-39; as individuais só o dono as vê) | `automation_rule`, `automation_vote`, `automation_log` | Moradores da casa | Sem expurgo | — |
| Segurança (alarme) | `domain_event` `safety.*` | Moradores da casa | Sem expurgo | — |
| Logs da aplicação | Ficheiros/consola do backend | Operação | Não definido | Só metadados, nunca pessoas, MAC, frames nem segredos |
| Segredos | `app/.env`, `app/.mcp-auth/` (fora do Git) | Operação | — | Nunca em logs, erros, testes nem docs |

**Nunca se guardam:** imagens, frames, rostos, endereços MAC em claro, URL RTSP, tokens em logs. A câmara só conta pessoas na soleira; **não tem consentimento individual** (não identifica ninguém).

## Direitos do próprio morador (o que o código faz)

| Direito | Como | Estado |
|---|---|---|
| Acesso / cópia | `GET /api/presence/export` (os meus dados de presença **e** o meu registo de consentimentos; nunca os de colegas) | IMPLEMENTADO |
| Escolha por fonte | Definições → «Presença e privacidade»: ligar/desligar Wi-Fi, aparelho a ligar, resposta manual, cada uma com o seu texto | IMPLEMENTADO |
| Apagar | Desligar uma fonte apaga só essa; desligar o opt-in global ou sair da casa apaga tudo de presença | IMPLEMENTADO (a eliminação por saída/global corre numa varredura de ≤ ~10 min; a recolha para logo) |
| Retificação, oposição, limitação | Sem fluxo próprio | **PLANEADO / por decidir** |

## Política de backups — **PROPOSTA (não implementada, não validada)**

O código não faz backups. Um backup anterior a uma eliminação **ainda tem os dados eliminados**: por isso:

1. Backup só de ficheiro SQLite da instalação, cifrado, fora do Git, com acesso restrito a quem opera a instalação.
2. **Prazo máximo de conservação dos backups: por decidir** com o DPO (P-08/P-25); até lá, nenhum backup com dados reais de pessoas (P-24).
3. **Restauro com reaplicação das eliminações:** depois de restaurar, repetir as eliminações pedidas desde o backup (o registo `presence_consent_log` e `presence_retention_log` dizem quem revogou/saiu e quando) antes de reabrir o serviço, e correr `make check`.
4. Os pedidos de eliminação feitos depois do backup têm de ser reaplicados no restauro: manter uma lista (consentimentos revogados, saídas) fora do backup.
5. Testar o restauro antes do piloto (**NÃO VERIFICADO**: nunca foi feito).

## O que continua por decidir (não inventado aqui)

- Prazos de retenção definitivos (P-08, P-20, P-25): presença (30 dias é PROPOSTA), agregados, registos de auditoria e de consentimentos, notificações, financeiros (prazo legal), backups.
- Gate jurídico (P-24): base legal por finalidade, responsável pelo tratamento, informação a moradores e visitantes, sinalização, AIPD.
- Votação da câmara (P-29) e sal por casa do `match_key` (P-30).
