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
desativadas por `ENABLE_PHYSICAL_WRITES=false`. Além do flag, `McpHome` exige um callback de
aprovação por ação; o motor atual não fornece esse callback, portanto ativar apenas o flag não
autoriza escritas automáticas de regras ou temporizadores.

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

## Limites da evidência

- Leituras de `get_home_devices` e `get_device_details` foram efetuadas; nenhuma escrita física foi
  chamada.
- A confirmação de escritas por releitura está implementada, mas depende do flag e de um callback
  explícito de aprovação por ação. Esse callback ainda não está ligado a um ActionExecutor e
  nenhuma escrita foi exercitada.
- A unidade de `instantPower` não consta no schema/resposta observados. Consumo em watts não está
  validado.
- `get_home_devices` e `get_device_details` são as fontes de estado; os tempos `lastCommunicationTime`
  são devolvidos pelo servidor, mas o polling ObjectOS regista separadamente o instante da sua
  última leitura.
