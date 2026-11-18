# Riscos técnicos e limites do hardware

Evidência detalhada em [integrations/mcp-capabilities.md](../integrations/mcp-capabilities.md). Estado a 17/11/2026, herdado do ObjectOS; **não foi reverificado nesta tarefa**. Riscos do PDF (§15.1, §24) incluídos onde se mantêm.

## Limites do hardware (factos observados)

| Limite | Evidência | Impacto na Conta Certa | Mitigação |
|---|---|---|---|
| **Unidade de `instantPower` não declarada** (`value`, `min 0`, `max 50000`; sem unidade; `techInfo` não ajuda). **Confirmada em W por medição** (MCP-01 #12, 17/11/2026; referência = etiqueta da cafeteira, sem confirmação dos mentores). A tomada reporta de ~30 em ~30 s | `mcp-capabilities.md` | Com `MCP_INSTANTPOWER_UNIT=W` há `measured`; a resolução dos degraus é da ordem de 30 s (ENERGY-02) | `MCP_INSTANTPOWER_UNIT=W`; simulador e potência nominal × estado (`estimated`) como plano B |
| **Uma só tomada com medição** | PDF §6.1, kit | Sem quartos medidos; identificação só por assinatura | Papel `main_meter`; quartos simulados; nunca prometer identificação perfeita |
| **Escrita física não comprovada** na lâmpada (resposta «device updated», sem efeito; `lastCommunicationTime` antigo e a crescer) | PR #57, `mcp-capabilities.md` | Feedback por cor e «desligo?» não podem ser REAL | Verificar MCP-04/05; tratar como simulado até PASS |
| **Tomada nunca testada** para escrita (`multiPower` com `switch_1`) | idem | Corte do aquecedor incerto; corta a extensão inteira | `make mcp-verify what=plug` com carga segura; dizer «em produção cada quarto tem a sua tomada» |
| Latência MCP (~0,65–0,87 s por leitura; 1.ª chamada ~2 s) | `mcp-demo.md` §9 | Degraus com resolução de ~5 s | Aparelhos ligados ≥ 2 min na demo |
| `lastCommunicationTime` antigo | `mcp-capabilities.md` | Dispositivos podem estar offline na cloud | Mostrar «sem contacto há N min»; `unknown`, nunca valor inventado |
| Câmara do kit: acesso à imagem não provado para este uso; fixa | PDF §5.5; só leitura RTSP via relay medida | Contagem na porta incerta | Telemóvel como câmara IP / clip; presença manual |
| Sensores de contacto/clima e alarme: **fora da política MCP atual** | `CLAUDE.md`, `mcp_home.py` | Automação «janela → corte», casa vazia armada | Ficam P2 e dependem de decisão P-01 |

## Riscos técnicos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Unidade de potência nunca confirmada antes da demo | Média | Alto | Plano B por simulador, anunciado como tal |
| Identificação errada de aparelho com um só medidor (aparelhos < 100 W, cargas sobrepostas, aparelhos iguais) | Alta | Médio | `confidence` + `unknown` + pergunta na aplicação; resíduo por igual |
| Persistência nova (SQLite) e barramento atrasam P1–P4 | Média | Alto | P5 entrega `core/db` e `core/events` primeiro; testes com base em memória |
| Divergência de contratos entre 5 pessoas em paralelo | Média | Alto | [Definição de pronto dos contratos](roadmap.md); PRs de contrato pequenos e revistos por P5 |
| Ordem de arranque alfabética dos `lifespan` | Média | Médio | Recursos partilhados em `core/`; sem dependência entre features ([overview.md](../architecture/overview.md)) |
| LLM a inventar números | Média | Alto | Guarda-corpos: números só de ferramentas ([agent.md](../modules/agent.md)) |
| Dados de consumo enviados a um LLM externo | Média | Médio (privacidade) | Dados mínimos; decisão P-06; assistente opcional |
| Presença contraditória (dados móveis, PC a correr) | Média | Médio | Tolerância de 20–30 min; estado `uncertain`; pergunta |
| Contestações sem processo definido | Média | Médio | `Attribution` auditável e `superseded`; processo mínimo em P1 |
| Fixtures do PDF confundidas com resultados nossos | Média | Alto (credibilidade) | Rotulados «ilustrativos do PDF»; fatura de demo `simulated` |
| Sem testes automáticos de frontend | Alta | Médio | Validação manual pelo guia; avaliar testes de componentes (P-12) |
| Prazos da organização por confirmar | — | Alto | Confirmar (P-11) |

## Riscos legais e de produto (do PDF; não validados por nós)

| Risco | Nota |
|---|---|
| Câmara percebida como vigilância; consentimento; RGPD (AIPD, DPO, pictograma) | PDF §5, §10: **não é aconselhamento jurídico**; validar com jurista antes de qualquer piloto |
| O senhorio só pode repartir o custo real (vender eletricidade é regulado) | PDF §10.3 |
| Incentivo a passar frio | Plafond solidário (prioridade P1) |
| Senhorio a querer controlar inquilinos | DTOs sem presença nem aparelhos; testes de permissões |
| «Não conhecemos solução semelhante em Portugal — confirmar» | PDF §23: afirmação por validar |

## O que nunca fazer perante um bloqueio

Não declarar uma ferramenta MCP funcional sem evidência; não repetir uma escrita de resultado incerto; não apresentar simulação como real; não relaxar a whitelist (3 ferramentas; lâmpada e tomada) nem a política de escritas físicas; em dúvida de segurança, autenticação ou hardware, o comportamento mais restritivo.
