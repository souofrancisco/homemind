# HOUSE-03 — Catálogo de aparelhos e medidores (issue #86)

**Estado:** implementação proposta no Draft PR, sem merge. O catálogo não implementa NILM (P1),
consumo (P1) nem atribuição financeira (P4). F0 permanece como fonte de verdade para os
tipos `Device`, `Appliance`, `ApplianceSignature`, `ConsumptionEvent` e autorização.

## Investigação das três alternativas

| Critério | A — relacional simples | B — relacional temporal | C — orientado a assinatura |
|---|---|---|---|
| Simplicidade | Alta | **Média** | Baixa |
| Integridade referencial | Alta com FKs | **Alta com FKs e índices** | Depende da estrutura |
| Histórico de dono/local/medidor | Não, exige auditoria externa | **Sim, intervalos imutáveis** | Parcial, requer versões |
| Compatibilidade NILM | Só com extensões | **Boa, assinatura independente** | Ótima |
| Consulta REST/SQLite | Muito fácil | **Fácil, JOIN + janela temporal** | Mais joins e consultas especializadas |
| Dois aparelhos na mesma tomada | Sim com N:1 | **Sim com N:1 histórica** | Sim |
| Várias tomadas por quarto | Sim | **Sim; sem restrição device/room** | Sim |
| Impacto na fatura | Risco de reescrever passado | **Snapshot por instante do evento** | Exige separar classificação/cobrança |
| Trabalho adicional P1/P4 | Alto para histórico | **Moderado, contrato claro** | Alto para uma hackathon |

**Escolha: B mínima, com separação de sensores/ativos inspirada em C.** `Appliance` é o
ativo consumidor, `Device` é o medidor/atuador; `ApplianceSignature` pertence ao algoritmo P1.
Só as três relações relevantes para auditoria são temporais: propriedade/âmbito,
divisão habitual e medidor associado. Não introduzimos um grafo RDF, event sourcing novo
ou biblioteca extra. Um único `main_meter` pode ser ligado a muitos aparelhos.

**Fontes verificáveis:**
- [Brick Ontology — relações entre equipamento, espaços e pontos](https://docs.brickschema.org/brick/relationships.html):
  separa ativos físicos de pontos de telemetria e localização.
- [Project Haystack — Equipment](https://project-haystack.org/doc/docHaystack/Equips) e
  [Points](https://project-haystack.org/doc/docHaystack/Points):
  referências distintas a equipamento, local e sensores.
- [NILM: challenges of overlapping loads](https://www.mdpi.com/1996-1073/19/8/1883):
  assinaturas de aparelhos podem sobrepor-se e a identificação é probabilística.
- [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html) e
  [partial indexes](https://www.sqlite.org/partialindex.html):
  FKs compostas e unicidade parcial para a relação atual.

## SQLite implementado (`0101_house_appliance_catalog.sql`)

| Tabela | Chaves e invariantes |
|---|---|
| `device` | UUID interno, FK casa, FK composta casa/quarto, `source`, `external_ref` **interno**, `kind`, `role`, `power_unit`; unicidade de identidade externa dentro da casa |
| `appliance` | UUID interno, FK casa e registante, nome, categoria, potência opcional, `created_at`, `retired_at`, estado; unicidade de registo ativo com mesmo registante/nome/categoria |
| `appliance_state` | FK composta aparelho/casa + quarto/casa, `scope`, proprietário opcional, `home_room_id`, `valid_from`, `valid_to`; um único estado atual por aparelho |
| `appliance_meter_link` | FK composta aparelho/casa e medidor/casa; N aparelhos → 1 medidor; um único medidor habitual ativo por aparelho; links históricos preservados |
| `appliance_signature` | Dados opcionais de `ApplianceSignature`, FK aparelho; P1 escreve e classifica, sem garantir identidade |

O período é semiaberto `[valid_from, valid_to)`; leituras da base usam timestamps UTC
normalizados. Mudança de contexto encerra a versão anterior e cria outra na **mesma
transação**. Índices únicos parciais impedem duas versões atuais; triggers impedem
apagar ou modificar versões encerradas. A aplicação impede janelas de duração zero
(`409 catalog_time_conflict`) e valida proprietários como **inquilinos ativos no fuso
da casa**, e divisões como pertencentes à mesma casa. Uma pessoa que abandone a casa
não elimina estados históricos.

A coluna `home_room_id` é **divisão habitual**, não a prova de onde o aparelho foi
utilizado. O `device.room_id` indica a localização configurada do medidor. Num
`ConsumptionEvent`, `location`/`room_id` são a observação de P1, potencialmente
desconhecida. Nenhuma das três dimensões implica o pagador.

## Rotas (prefixo `/api/households/{household_id}`)

| Método | Rota | Autorização |
|---|---|---|
| GET | `/appliances` | Tenant: próprios + comuns; operador: diagnóstico sem pessoas; senhorio: 403 |
| POST | `/appliances` | Tenant: registo pessoal/partilhado para si, ou comum |
| GET | `/appliances/{id}` | Tenant: próprios + comuns; operador: diagnóstico |
| PATCH | `/appliances/{id}` | Proprietário atual; ou autor de aparelho comum |
| DELETE | `/appliances/{id}` | Mesma regra; apenas soft-retire |
| GET | `/appliances/{id}/history` | Mesma leitura, proprietários de terceiros ocultados |
| GET | `/devices` | Operador, `DeviceView` sem `external_ref` |
| POST | `/devices/demo` | Operador; **só fake/replay**, nunca provisiona hardware |
| PUT | `/appliances/{id}/meter` | Operador; associa ou desassocia medidor existente |

Todos os endpoints usam `require_access` do F0: utilizador não-membro da casa ⇒ 404;
papel não autorizado ⇒ 403. Um tenant não pode ver aparelhos pessoais de outro
tenant. O operador não recebe nomes de aparelhos, proprietários ou autores.
Sem `sub` do Authentik, `external_ref` MCP, chaves ou telemetria privada nos DTOs.

**Exemplo de criação (inquilino autenticado):**
```json
{
  "name": "Aquecedor",
  "category": "heating",
  "scope": "personal",
  "home_room_id": "00000000-0000-0000-0000-000000000002",
  "typical_watts": 2000
}
```
`owner_resident_id` NÃO é aceite no registo: é obtido da membership autenticada.
Ao transferir o aparelho, o proprietário atual pode fazer
`PATCH {"owner_resident_id":"<uuid de outro inquilino ativo>","home_room_id":"<uuid sala>"}`;
o servidor nunca altera versões anteriores. Para `scope=common` o proprietário é
obrigatoriamente `null`. O operador pode associar:
```json
{"device_id": "00000000-0000-0000-0000-000000000003"}
```
ou desligar a associação com `{"device_id":null}`. Estes UUIDs são ilustrativos.

## Contratos estáveis para P1 e P4

**P1 (energia/assinaturas):**
- Pode provisionar um dispositivo descoberto pelo MCP com
  `features.appliances.repo.register_device(conn, Device(...))`, dentro de
  `db.run`/`run_sync`; a chave `external_ref` permanece privada. A API
  `/devices/demo` não serve de integração MCP.
- Usa `appliance_signature` e o modelo canónico `ApplianceSignature` para
  aprender/classificar; HOUSE-03 **não** fornece um classificador, treino nem
  ingestão de potência. P1 gere a escrita de assinaturas.
- `meter_at(conn, appliance_id, ts)` é **associação configurada**, não prova
  de que um único aparelho estava ativo. Com uma única tomada, vários
  candidatos e `unknown` são resultados legítimos.
- Mantém `ApplianceMatch` com `confidence` e candidatos no `ConsumptionEvent`;
  pode conter dois aparelhos de potência muito próxima e não escolher vencedor.

**P4 (faturação):**
- `context_for_consumption(conn, event: ConsumptionEvent)` devolve o
  `ApplianceOwnership` válido em `event.started_at`, ou `None` se
  `match.appliance_id` for `None` ou o aparelho não existir nesse instante.
  Em alternativa: `ownership_at(conn, household_id, appliance_id, ts)`.
- O histórico preserva proprietário e divisão no passado; a **localização do
  evento**, o utilizador real e a regra de atribuição vêm de evidências separadas.
  **Proprietário ≠ utilizador ≠ pagador**. A `confidence` da classificação
  não é uma decisão financeira nem prova de identidade.
- Nunca consultar o proprietário **atual** para reprocessar faturas antigas.
  `Attribution` e `BillAllocation` continuam exclusivamente em P4,
  com revisão explícita se existir contestação.

## Ensaios e limitações

`features/appliances/tests/test_catalog.py` cobre registos pessoais/comuns,
isolamento multi-casa e por papel, mudança de quarto/proprietário, consulta por
`ConsumptionEvent.started_at`, dois aparelhos com assinaturas próximas,
uma tomada para dois aparelhos, ausência de assinatura, soft-retire e saída
de um inquilino sem eliminar história. Testes com DB `:memory:`, clock fixo
e source `fake`; nenhum ensaio prova identificação real numa tomada Altice.

**Limites assumidos:** um aparelho tem no máximo um **medidor habitual** em cada
instante, mas o mesmo medidor pode agregar vários aparelhos; isto não impede que P1
reconheça a assinatura noutro medidor. Um histórico com alterações retroativas
(backdating) não é aceite pelo CRUD: exige revisão explícita, para impedir que se
reinterpretem silenciosamente períodos faturados. Alterações a uma divisão ou
proprietário fora da casa são rejeitadas antes de gravar.
