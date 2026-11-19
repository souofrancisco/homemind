# Real, estimado e simulado

Cada valor na aplicação, nos recibos e nos documentos tem uma origem. **Nunca se apresenta simulação como real.**

| Proveniência | Significado |
|---|---|
| `measured` | Medição real do dispositivo, com unidade confirmada |
| `estimated` | Calculado, por exemplo a lâmpada: 9 W × tempo × brilho |
| `inferred` | Deduzido (identificação de aparelho): vem sempre com `confidence`, nunca «certo» |
| `simulated` | Vem do simulador (FakeHome), do seed ou de um clip |

## O que é real na demonstração

| Componente | Real se… | Senão |
|---|---|---|
| Leituras da tomada | A unidade de `instantPower` está confirmada | Simulador ou potência nominal × estado (`estimated`) |
| Corte de uma tomada | A escrita foi comprovada com releitura | Simulado, dito como tal |
| Feedback da lâmpada | A lâmpada reage fisicamente (validado) | Só no ecrã; não se promete |
| Identificação de aparelho | Nunca «real» | Sempre `inferred` com confiança |
| Outros quartos | Nunca real no MVP (uma só tomada) | `simulated` |
| Presença | Registo manual real; câmara só se comprovada | Passagens simuladas |
| Fatura e recibos | O cálculo é real, em código, sobre dados com proveniência; **a fatura de demonstração é simulada** | Rótulo SIMULADO nos recibos |

**Regra:** nenhum passo se descreve como REAL sem validação registada nesse dia. Hoje, nenhum fluxo da aplicação foi validado com hardware real ponta a ponta.

## Plano B

Sem kit, MCP ou rede, a demonstração corre com `HOME_BACKEND=fake` e leituras simuladas. Serve para demonstrar a lógica de atribuição e de fatura de forma determinística, e diz-se sempre em voz alta.

*Fontes canónicas: `docs/development/mvp.md`, `docs/architecture/data-model.md`.*
