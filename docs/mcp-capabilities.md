# Altice MCP — capacidades observadas

Observado em `2026-11-17` através da sessão OAuth própria do ObjectOS. `initialize()` e
`tools/list` concluíram com sucesso. A descoberta e leituras abaixo vieram do servidor real;
identificadores externos e informação de vendor foram omitidos. Nenhum comando de escrita foi
executado.

## Ferramentas devolvidas por `tools/list`

| Nome exato | Parâmetros de entrada observados |
| --- | --- |
| `get_device_details` | `deviceId` obrigatório; `techInfo` boolean opcional; `vendor` string opcional |
| `get_device_recommendations` | sem parâmetros |
| `get_device_timers` | `deviceId` obrigatório |
| `get_home` | sem parâmetros |
| `get_home_detail_report` | sem parâmetros |
| `get_home_devices` | sem parâmetros |
| `get_home_rooms` | sem parâmetros |
| `get_home_scenarios` | sem parâmetros |
| `get_home_security_alarm_history` | `size` e `page` obrigatórios; `startDate` e `endDate` inteiros opcionais |
| `get_home_security_status` | sem parâmetros |
| `get_home_status_brief` | sem parâmetros |
| `get_scenario` | `scenarioId` obrigatório |
| `patch_home_security_status` | `body` obrigatório; altera estado de segurança e não é permitido pelo ObjectOS |
| `patch_scenario_activation` | `scenarioId` obrigatório; estado/cenário opcional |
| `post_execute_scenario` | `scenarioId` obrigatório |
| `post_new_scenario` | objeto de cenário com triggers e start/end actions |
| `post_timer_device` | `deviceId` e `body` obrigatórios |
| `update_device_capabilities` | `body` obrigatório; `deviceId` ou `deviceName` e `vendor` opcionais |

## Schemas relevantes observados

### `get_home_devices`

Entrada vazia. A resposta estruturada observada é um objeto `{ "devices": [...] }`. Cada
dispositivo devolve `id`, `name`, `type`, `capabilities` e pode incluir categorias, sala e datas
de comunicação/associação. Cada capability observada tem `type`, `value` e, conforme a
capacidade, `min`, `max`, `availableValues` e canais RGB.

### `get_device_details`

Entrada: `{ "deviceId": string }`. Devolve um objeto de dispositivo com `id`, `name`, `type`,
`capabilities`, `pairedTime` e `lastCommunicationTime`; `roomName` é opcional. IDs e sala foram
omitidos neste documento.

### `update_device_capabilities`

O schema de `body` é uma união de variantes. Para as duas classes de dispositivo observadas e
permitidas pelo conector:

```json
{"deviceId":"<descoberto em runtime>","body":{"type":"power","value":"on"}}
{"deviceId":"<descoberto em runtime>","body":{"type":"brightness","value":50}}
{"deviceId":"<descoberto em runtime>","body":{"type":"color_rgb","redValue":255,"greenValue":0,"blueValue":0}}
```

O schema também anuncia `temperature`, mas o conector não permite essa operação. O ObjectOS não
usa ferramentas de alarme/segurança, cenários ou timers. Atualizações físicas continuam
desativadas por `ENABLE_PHYSICAL_WRITES=false`. Além do flag, `McpHome` exige um grant temporário
criado pelo operador (`make mcp-writes-on`, ver `docs/mcp-demo.md`), partilhado pelo motor e pelo
`McpHome`; expirado ou revogado, todas as escritas são recusadas. A whitelist é exata:
`get_home_devices`, `get_device_details`, `update_device_capabilities`; lâmpada `power`,
`brightness`, `color_rgb`; tomada só `power`. Os schemas são validados antes da primeira chamada.

## Inventário obtido por leitura MCP

`get_home_devices` devolveu os seguintes tipos e nomes genéricos. A seleção da lâmpada e da tomada
no código é feita pelas capabilities, nunca pelos IDs ou nomes.

| Nome devolvido | `type` | Observação relevante |
| --- | --- | --- |
| Smoke sensor | `smokeSensor` | Segurança; fora da whitelist de controlo |
| Temperature sensor | `temperatureSensor` | Leitura não utilizada nesta integração |
| Camera | `camera` | Não acedida pela integração |
| Plug | `plug` | Categoria `energy` e capability `power` |
| Light | `bulb` | Capacidades RGB, brilho e energia da lâmpada |
| Security hub | `gateway` | Segurança; fora da whitelist de controlo |
| Contact sensor | `contactSensor` | Segurança; fora da whitelist de controlo |

Na resposta real da tomada (`get_device_details`), foram observadas as capabilities
`additionalEnergyConsumption`, `instantCurrent`, `instantPower`, `instantVoltage`, `multiPower`,
`power`, `todayConsumption` e `yesterdayConsumption`. `power` usa `availableValues: ["on",
"off"]`. `instantPower` inclui um valor numérico e min/max, mas a resposta e o schema MCP não
declaram unidade. Por isso o estado ObjectOS mantém `consumo_w: null` até a unidade ser confirmada;
não converte nem apresenta o valor bruto como watts. A leitura é consultada em polling de 5 s e
`ler_consumo()` apenas devolve o cache.

Na resposta real da lâmpada (`get_device_details`), foram observadas:

| Capability | Formato/limites observados |
| --- | --- |
| `power` | `"on"` ou `"off"` |
| `color_rgb` | `redValue`, `greenValue`, `blueValue`, cada canal 0–255 |
| `brightness` | número entre 1 e 100 |
| `workMode` | valores disponíveis incluem `colour`, `music`, `white`, `scene` |
| `temperature` | número, min 0 e max 100; não é usado como brilho nem controlado |

## Consumo (`instantPower`, #12) — evidência e bloqueio

Evidência recolhida em leitura (2026-11-17), incluindo `get_device_details` com `techInfo: true`:

- A capability traz `value`, `min: 0`, `max: 50000` e nenhum campo de unidade; `techInfo` não
  devolve fabricante/modelo/unidade.
- `instantVoltage` = 234 (max 50000) e `instantCurrent` = 0 (max 30000): as escalas dos máximos não
  são coerentes com V/A/W inteiros; com 50000 em W seriam 50 kW, implausível para uma tomada.
  Compatível com décimas de W, mW ou W — não distinguível.
- Com a tomada em vazio `instantPower` = 0, logo não dá para comparar `V × I` com a potência.

**Não confirmado:** a unidade de `instantPower`. `consumo_w` mantém-se `null`. Perguntar aos
mentores da Altice: (1) a unidade de `instantPower` (W, 0,1 W ou mW) e das capabilities
`instantVoltage`/`instantCurrent`; (2) se `todayConsumption` é kWh. Alternativa interna: ligar uma
carga conhecida (ex.: 60 W) e comparar `instantPower` com `instantVoltage × instantCurrent`.
Confirmada a unidade, basta acrescentá-la em `_UNIT_FACTOR` (`mcp_home.py`); o polling,
timestamp e limpeza em falha já estão implementados.

## Verificação física da lâmpada (#10/#11) — 2026-11-17, BLOQUEADA

Executada com autorização explícita do operador (`make mcp-verify what=lamp`, grant privado de
2 min só para a lâmpada), estado inicial restaurado no fim. Resultado:

- Descoberta inequívoca: 1 lâmpada RGB e 1 tomada (por capabilities, sem IDs).
- `update_device_capabilities` devolveu `{"message": "device updated"}` (`isError=false`) para
  `color_rgb` e `brightness`; a lâmpada **física não mudou** e a releitura (até 12 s) manteve o estado
  inicial. Numa tentativa anterior a releitura chegou a mostrar a alteração (RGB×brilho) durante ~12 s
  e depois voltou ao inicial. `lastCommunicationTime` da lâmpada tinha ~3 min.
- O `McpHome` comportou-se como desenhado: **não** deu a escrita como sucesso («estado final não
  corresponde ao pedido») e o restauro ficou confirmado. Não há evidência de controlo físico: #10 e
  #11 mantêm-se por fechar.
- A confirmar com os mentores/hardware: se a lâmpada está acessível pela cloud (ligação Wi-Fi,
  reset/pareamento), se `workMode` tem de ser `colour`/`white`, e se `update_device_capabilities`
  é assíncrono (ack ≠ aplicado).
- Observado: o `color_rgb` lido vem **escalado pelo brilho** (RGB × brilho/100). O `McpHome` confirma
  a cor contra o RGB escalado e publica o RGB normalizado (cor a 100 %), como o FakeHome.

## Limites da evidência

- Leituras de `get_home_devices` e `get_device_details` foram efetuadas. Escritas: ver a
  verificação física acima (sem efeito físico confirmado); a tomada não foi testada.
- A unidade de `instantPower` não consta no schema/resposta observados. Consumo em watts não está
  validado.
- `get_home_devices` e `get_device_details` devolvem as mesmas capabilities (comparado em leitura).
  O polling ObjectOS regista separadamente o instante da sua última leitura.
- Latência observada: 1.ª chamada de cada sessão ~2 s, seguintes ~0,5–0,8 s.
