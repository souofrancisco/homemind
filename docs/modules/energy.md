# Módulo `devices` + `energy` — dispositivos, leituras e assinaturas

**Dono: P1 (brunovieira88).** **PLANEADO**, sobre código existente em `connectors/`. Integração MCP: [integrations/altice-mcp.md](../integrations/altice-mcp.md).

## Responsabilidade

1. Falar com o kit (MCP) ou com o FakeHome/simulador e produzir `EnergyReading` com proveniência.
2. Detetar degraus de potência e episódios de consumo.
3. Identificar o aparelho por assinatura (com confiança), localizar (quarto ou zona comum) e emitir `ConsumptionEvent`.
4. Executar ações físicas autorizadas (corte da tomada, cor da lâmpada) pelo contrato `Home`.

## Recebe / produz

| Recebe | Produz |
|---|---|
| Polling do MCP (a cada 5 s, já implementado) ou do simulador | `EnergyReading`, `energy.reading_recorded` |
| Aparelhos registados e assinaturas (UI/API) | `PowerStep`, `energy.step_detected` |
| Respostas de confirmação (para aprender) | `ConsumptionEvent`, `energy.consumption_detected`, `energy.consumption_closed` |
| Ordens de ação confirmadas (agente, automações) | Escritas via `Home` com a whitelist atual |

## Pipeline (PDF §6.3, adaptado)

| Passo | Implementação inicial | Prioridade |
|---|---|---|
| Registo de aparelhos (nome, dono, âmbito, potência típica) | API + formulário | P0 |
| Deteção de degraus | Diferença entre janelas de leituras, limiar configurável; ΔW mínimo (PDF sugere > 300 W para a demo) | P0 |
| Identificação | Vizinho mais próximo sobre (potência, duração, padrão), devolve `confidence` e candidatos; abaixo do limiar → `unknown` | P0 |
| Localização | **MVP:** pela zona registada do aparelho e pela tomada principal (`main_meter`); com `room_meter` no futuro, pela tomada do quarto que mudou | P0 |
| Aprendizagem com confirmações | Atualiza `ApplianceSignature` (`origin=learned`) | P1 |
| Aparelhos desconhecidos recorrentes (clustering) | Agrupar degraus semelhantes e perguntar uma vez | P2 |
| Estimativa de lâmpada (9 W × tempo × brilho) | `provenance=estimated` | P2 |

## O que não se promete

Com **uma só tomada de medição** o sistema separa cargas com potências bem distintas (aquecedor ~2000 W vs secador ~600 W), mas **não** garante a identificação de aparelhos pequenos (< 100 W), de dois aparelhos em simultâneo com potências próximas, nem a distinção de dois aparelhos iguais em quartos diferentes. O resultado tem sempre `confidence` e pode ser `unknown`; o resíduo divide-se por igual. Os próprios autores do PDF dizem que o NILM «funciona para cargas grandes» (§15.1).

## Estado do hardware que condiciona este módulo

| Facto | Estado (ver [mcp-capabilities.md](../integrations/mcp-capabilities.md)) | Consequência |
|---|---|---|
| Unidade de `instantPower` | **Não declarada** (valor, min 0, max 50000, sem unidade) | Sem `MCP_INSTANTPOWER_UNIT`, `power_w = null` e **não há `measured`**. Calibrar com carga conhecida |
| Escrita na lâmpada | Resposta «device updated» mas **efeito físico não comprovado** | Feedback por cor e «desligo?» não podem ser afirmados REAL |
| Escrita na tomada | **Nunca testada** (`multiPower` com `switch_1`) | Corte do aquecedor só com MCP-05 aprovado |
| Latência | ~0,65–0,87 s por leitura; ~0,9 s por ciclo | Degraus a 5 s de resolução; aparelhos ligados ≥ 2 min na demo |

Plano alternativo (PDF §20 #2): se não houver watts, potência nominal × estado ligado/desligado, com `provenance=estimated`.

## Ficheiros existentes reutilizáveis

`connectors/mcp_home.py`, `altice_auth.py`, `altice.py`, `write_grant.py`, `mcp_verify.py`, `fake_home.py`, `contracts/home.py`, `contracts/simulacao.py`, `features/mcp/router.py`; Makefile `mcp-*`.

## Ficheiros novos previstos

`features/devices/`, `features/energy/{steps,signatures,locate,router,service,tests}`, `contracts/energy.py`. O simulador de leituras e o replay de um mês ficam em `features/energy/simulation.py` (**PROPOSTA**).

## Dependências

Precisa de P5 (`core/db`, `core/events`, `households` para `Appliance.owner`). Alimenta P4 e P3.

## Critérios de aceitação

- Com o simulador, três aparelhos de potências distintas ligados em sequência geram os `ConsumptionEvent` esperados (nomes e confiança acima do limiar) em CI, sem hardware.
- Um degrau sem correspondência gera `unknown` e nunca um aparelho inventado.
- Com MCP real: leitura de `instantPower` só vira `measured` depois de a unidade estar confirmada e registada.
- Nenhuma escrita física sem flag + grant + autorização (regra já implementada, mantém-se).

## Testes

Tudo com `FakeHome` e relógio simulado (sem rede nem hardware): degraus, histerese, dois aparelhos simultâneos, termóstato a ciclar, desligar sem leitura. Hardware só pelo [guia de validação](../development/guia-validacao-manual.md) (MCP-03, MCP-05, MCP-06), com registo do resultado lá.
