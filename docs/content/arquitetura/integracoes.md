# Integrações com dispositivos

A integração com o kit Connected Home da Altice faz-se pelo **MCP**, atrás de um protocolo `Home` com duas implementações: `McpHome` (hardware) e `FakeHome` (simulado).

## Regras do MCP

- Ferramentas usadas: apenas `get_home_devices`, `get_device_details` e `update_device_capabilities`.
- Dispositivos: apenas lâmpada (`power`, `brightness`, `color_rgb`) e tomada (`power`). Sensores só em leitura (`unknown` se não suportado).
- Alarme, segurança, cenários e timers não são escritos pela aplicação. A leitura do estado de segurança é a única exceção, só de leitura.
- **Escritas físicas:** `ENABLE_PHYSICAL_WRITES=false` por omissão e autorização temporária. Uma escrita só se confirma por **releitura**; uma escrita de resultado incerto **nunca** é repetida.

## Estado da evidência

| Aspeto | Estado |
|---|---|
| Política de escrita por regra (`WriteResult`: confirmed / refused / failed / unknown) | <span class="estado estado--ok">IMPLEMENTADO</span>, sem escritas físicas executadas |
| Leituras reais do MCP | Provadas em medições de 17/11/2026, herdadas e não reverificadas |
| Escritas físicas (lâmpada, tomada) | Não comprovadas |
| Leitura real do estado do alarme | Vista no browser a 2026-11-19 com casa marcada «real» numa cópia local; o estado físico não foi confirmado por uma pessoa |
| Validação com o kit real ponta a ponta | <span class="estado estado--plan">PLANEADO</span> |

## Outras fontes

- **Câmara na porta:** só conta entradas e saídas; nunca grava. Sem câmara, a presença faz-se por Wi-Fi opt-in ou resposta manual.
- **Simulador (`FakeHome`):** reproduz leituras de aparelhos com perfis conhecidos; tudo o que gera é marcado `simulated`.
- Contador geral (HAN / E-REDES) e MEO Energia: fora do MVP.

*Fontes canónicas: `docs/integrations/altice-mcp.md`, `docs/integrations/mcp-capabilities.md`.*
