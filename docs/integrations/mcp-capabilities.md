# Altice MCP — capacidades observadas

> **Nota (Conta Certa):** observações de hardware, bloqueios e hipóteses de 17/11/2026, **preservadas**. Continuam a ser a evidência de referência. Ponto de entrada: [altice-mcp.md](altice-mcp.md).

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
criado pelo operador (`make mcp-writes-on`, ver [mcp-demo.md](mcp-demo.md)), partilhado pelo motor e pelo
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
declaram unidade. A unidade foi **confirmada em W** por medição (ver «Consumo (`instantPower`, #12)»
abaixo), mas o estado ObjectOS só converte o valor se `MCP_INSTANTPOWER_UNIT` estiver definida:
sem ela `consumo_w` mantém-se `null` e o valor bruto não é apresentado como watts. A leitura é
consultada em polling de 5 s e `ler_consumo()` apenas devolve o cache.

Na resposta real da lâmpada (`get_device_details`), foram observadas:

| Capability | Formato/limites observados |
| --- | --- |
| `power` | `"on"` ou `"off"` |
| `color_rgb` | `redValue`, `greenValue`, `blueValue`, cada canal 0–255 |
| `brightness` | número entre 1 e 100 |
| `workMode` | valores disponíveis incluem `colour`, `music`, `white`, `scene` |
| `temperature` | número, min 0 e max 100; não é usado como brilho nem controlado |

## Consumo (`instantPower`, #12) — unidade confirmada em W (2026-11-17)

**Resultado: CONFIRMADO — `instantPower` em W, `instantVoltage` em V, `instantCurrent` em mA.**
A confirmação é por medição com carga de referência; **não** foi confirmada pelos mentores da
Altice nem por documentação do fabricante (a capability continua sem campo de unidade).

Evidência anterior, em leitura, incluindo `get_device_details` com `techInfo: true`: a capability
traz `value`, `min: 0`, `max: 50000` e nenhum campo de unidade; `techInfo` não devolve
fabricante/modelo/unidade. Os máximos (50000 em W seriam 50 kW) não permitiam concluir a unidade, e
com a tomada em vazio (`instantPower` = 0) não havia como comparar com `V × I`.

### Procedimento (só leitura; sem escritas físicas)

Amostragem da tomada com `get_home_devices` (uma sessão MCP por amostra, a cada 3–4 s) e registo de
`instantPower`, `instantVoltage` e `instantCurrent`. Cada carga foi ligada pelo operador; nenhuma
foi comandada via MCP. O fator de potência aparente é `P / (V × I)` com `I` em mA.

### Valores de referência observados

| Carga | `instantPower` | `instantVoltage` | `instantCurrent` | V × I (VA) | P / (V × I) |
|---|---:|---:|---:|---:|---:|
| Portátil a 100 % com carregador de 45 W | 9–11 | 237 | 78–109 | 18,5–25,8 | 0,39–0,50 |
| Extensão com vários carregadores | 77 | 239 | 602 | 143,9 | 0,54 |
|  | 88 | 239 | 539 | 128,8 | 0,68 |
|  | 141 | 238 | 777 | 184,9 | 0,76 |
| **Cafeteira** (etiqueta 1850–2200 W, 220–240 V) | **2171** | **231** | **9334** | **2156** | **1,01** |

- **Carga de referência:** a cafeteira, uma resistência, deu 2171 no `instantPower`, dentro do
  intervalo da etiqueta (1850–2200 W). Em 0,1 W seriam 217 W (fora da etiqueta) e em mW seriam
  2,17 W (absurdo).
- **Coerência com V × I:** com a cafeteira `P / (V × I)` = 1,01 (carga resistiva, ~1; o desvio é
  arredondamento de inteiros). Com cargas eletrónicas fica entre 0,39 e 0,76, normal para
  carregadores; em 0,1 W seria ~0,05.
- **Limitações:** a referência de potência da cafeteira é a etiqueta (nominal), não um segundo
  medidor; o portátil e a extensão não têm potência nominal conhecida e só servem de coerência.

### Cadência e frescura (observado; amostra pequena)

- `lastCommunicationTime` é um epoch em **milissegundos com resolução total**. Em 8 leituras
  seguidas (a cada ~4 s) avançou **+30,0 s** e **+30,0 s** (30 016 ms e 29 968 ms): a tomada
  reporta com um batimento periódico de **30 s**. Houve ainda uma atualização extra **+2,2 s**
  depois, quando a carga mudou (135 → 110 W): além do batimento, há atualização por mudança.
  Observação de uma só série, sem período garantido pelo fabricante.
- Nas séries de potência, os valores ficavam parados cerca de 28–32 s entre mudanças, coerente
  com o batimento de 30 s.
- Consequência: a deteção de degraus (ENERGY-02) tem resolução da ordem de 30 s (mais fina só
  quando a carga muda), não a do polling de 3–5 s. A frescura de uma leitura calcula-se com
  `agora − lastCommunicationTime`; um limiar de «stale» deve ser um múltiplo do batimento (≥ 90 s).
- Latência por chamada com sessão nova: ~1,4–1,7 s (uma série) e 2,4–4,8 s (outra); varia com a rede.

### Configuração

Definir `MCP_INSTANTPOWER_UNIT=W` em `app/.env` e reiniciar o backend: o `McpHome` passa a converter
para W e `consumo_w` deixa de ser `null`. Se o MCP passar a declarar a unidade na capability
(`unit`/`unitOfMeasure`), essa tem prioridade sobre a variável. Vazia (por omissão) = `null`, com
aviso. Valores `dW` (0,1 W) e `mW` continuam suportados mas ficam excluídos para este kit.

### Por confirmar

(1) Com os mentores da Altice: a unidade documentada de `instantPower`/`instantVoltage`/
`instantCurrent`; (2) se `todayConsumption` é kWh (não medido aqui).

## Sensores do kit (MCP-03) — inventário e matriz (2026-11-17)

Inventário por `get_home_devices` (só leitura; sem IDs, nomes nem MACs). O kit tem 7 dispositivos; a lista e o detalhe (`get_device_details`) devolvem as **mesmas** capabilities em todos os sensores.

### Matriz por dispositivo: observado × suportado × simulado

| Dispositivo (`type`) | Capabilities observadas (valor/forma) | Observado | Adaptador | Simulado |
|---|---|---|---|---|
| **Contacto** (`contactSensor`) | `sensorState` (`normal`/`alarm`), `tamperState`, `batteryStatus` (`low`/`medium`/`high`) | **REAL**, confirmado fisicamente | `SensorReading` `contact` (IMPLEMENTADO) | **IMPLEMENTADO** (`FakeKit`, MCP-05) |
| **Clima** (`temperatureSensor`) | `temperatureValue` (min −50, max 60), `humidityValue` (0–100), `batteryLevel` (0–100) | **REAL** | `SensorReading` `temperature` + `humidity` (IMPLEMENTADO) | **IMPLEMENTADO** (`FakeKit`, MCP-05) |
| **Fumo** (`smokeSensor`) | só `batteryStatus` (sem estado de alarme) | REAL (só bateria) | **Fora de âmbito** (decisão do utilizador: o detetor de fumo não é usado) | — |
| **Gateway** (`gateway`) | `alarmState`, `tamperState`, `networkMode` (`ethernet`/`wifi`/`cellular`), `chargeState`, `batteryLevel`, `factoryReset` | REAL | Só estado, sem adaptador de decisão. **`factoryReset` nunca se escreve** | — |
| Câmara, tomada, lâmpada | ver secções anteriores | REAL | `McpHome` (já implementado) | FakeHome |

Todos os dispositivos de segurança (`categories` contém `security`: contacto, fumo e gateway) ficam **fora** do caminho de controlo do `McpHome` (`_find_devices` ignora-os); só se leem, sem escritas.

### Contacto — mapeamento verificado fisicamente

| Estado físico | `sensorState` | Leituras |
|---|---|---|
| Fechado (íman junto) | `normal` | 3 + 1 depois de fechar |
| Aberto (íman afastado) | **`alarm`** | 4 |

**`alarm` = aberto, `normal` = fechado.** Observado com o operador a abrir e fechar o sensor.
- O sensor reporta **por mudança de estado**. **Não há batimento regular observado**: no início da série tinha 199 s de idade e só reportou 344 s depois (com o sensor parado). Os reportes seguidos de 31–80 s com o mesmo estado vieram durante o manuseamento (o íman a mexer), não de um período fixo.
- **Latência (não medida com precisão)**: ao abrir, a mudança já estava reportada ~10 s depois do gesto. Ao fechar, o operador disse «fechei» antes das 22:11:56, as leituras seguiram em `alarm` e a mudança só foi reportada às 22:12:23: **≥ ~27 s**. Não se sabe a hora exata dos gestos. A meta «janela aberta → corte < 10 s» exige um teste cronometrado antes de ser prometida.
- Resposta com valor desconhecido/ausente = `unknown`; nunca se assume «fechado».

### Clima

- `humidityValue` está em % (intervalo declarado 0–100).
- `temperatureValue` **sem unidade declarada**: o valor lido (25,3) coincide com a temperatura do local indicada pelo operador (~25 °C), logo **°C** (verificação aproximada, sem termómetro calibrado; a escala −50…60 também é a de °C).
- Reporta devagar: sem nova atualização durante **7 min** de observação, depois de já ter ~4 min (≥ ~11 min entre reportes). Um limiar de `stale` do clima tem de ser de vários minutos e não os 90 s da tomada (provisório: 2 h, a afinar quando houver um período medido).

### Cadência de frescura observada (uma série de 7 min)

| Sensor | Observado |
|---|---|
| Contacto | por mudança de estado; sem batimento regular observado (344 s calado com o sensor parado) |
| Clima | ≥ ~11 min sem reportar |
| Fumo, gateway | sem reporte em 7 min; `lastCommunicationTime` já com ~1 h no início (batimento horário provável, não confirmado) |

### Adaptadores e collector (MCP-03) — **IMPLEMENTADO** (sem ligação à app)

- `connectors/mcp_sensors.py`: `sensor_readings_from_device` (função pura) converte `contactSensor` em 1 `SensorReading` e `temperatureSensor` em 2 (temperatura e humidade). Contacto `alarm` → `open`, `normal` → `closed`; qualquer outro valor, ausente ou fora de escala (temperatura fora de −40…85, humidade fora de 0…100, bool, NaN) → `unknown` sem valor: **nunca** se assume «fechado» nem um valor por omissão. Os outros tipos (fumo, gateway, tomada…) devolvem `[]`.
- `connectors/mcp_sensor_collector.py`: `SensorCollector` publica `SensorReadingRecorded` só quando algo muda. Contacto: (estado) — os reportes repetidos com o mesmo estado não geram eventos; clima: cada amostra nova (`observed_at`). Uma transição `ok → stale` publica uma vez; `unavailable()` esquece o estado; erros de `publish` ficam isolados.
- `McpHome.sensores` (opcional): com o collector definido, cada leitura faz **uma** chamada extra de **leitura** a `get_home_devices` e passa-lhe os dispositivos. Sem o collector não há nenhuma chamada extra. Os dispositivos de segurança continuam fora do caminho de controlo (`_find_devices`); não há escritas.
- **Por fazer (PLANEADO):** montar o collector no arranque da app (precisa de casa e dispositivos em BD: HOUSE-01/03) (o simulador de sensores já existe: ver «Simulador do kit»). Limiares de `stale` provisórios (2 h).

### Por confirmar

Latência real abrir/fechar do contacto (teste cronometrado); período de reporte (batimento) do contacto e do clima: os limiares de `stale` do adaptador (2 h para os três) são **provisórios** e foram escolhidos para não marcar como `stale` um sensor saudável e parado; se o alarme de fumo aparece no `alarmState` do gateway (fora de âmbito).

## Simulador do kit (MCP-05) — **IMPLEMENTADO**, tudo **SIMULADO**

`connectors/fake_mcp.py`: `FakeKit` responde como o kit real ao nível da **sessão MCP** (`get_home_devices`, `get_device_details`, `update_device_capabilities`, com os mesmos schemas que passam `_validate_tools`), logo o `McpHome`, os adaptadores e os collectors correm **sem alterações** e sem rede nem hardware.

- **Dispositivos** com o formato JSON observado no kit: tomada (`instantPower` em W sem campo de unidade, `instantVoltage`, `instantCurrent` em mA, `power`, `multiPower` com um interruptor `switch_1`), lâmpada, contacto (`alarm` = aberto) e clima. IDs fixos e claramente simulados (`sim-…`).
- **Cadência** como no kit: a tomada avança `lastCommunicationTime` em batimentos de 30 s e quando a carga muda; o contacto só quando muda. Relógio injetável (determinístico).
- **Cenário:** `set_load(watts)`, `open_contact()`/`close_contact()`, `set_climate(...)`, `reset()` (idempotente).
- **Erros controlados** (os observados no kit real): sessão em baixo, OAuth expirado, escrita recusada (`isError`), escrita aceite e ignorada (lâmpada H1), queda depois de enviar, dispositivo sem contactar a cloud e unidade declarada/ausente.
- **SIMULADO vs REAL:** os adaptadores e os collectors aceitam `origin` (por omissão `real`); com o simulador usa-se `Origin.simulated` e as leituras saem `simulated/measured`.
- **Limites:** tensão fixa em 230 V e fator de potência configurável (1,0 por omissão); `todayConsumption` não é simulado (fica 0). Com o simulador cria-se `McpHome(..., simulated=True)`: o estado sai com `backend="fake"` (a UI já o mostra como SIMULADO) e `mcp_ok` sempre `False`, como manda o contrato; sem contrato novo.

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

## Leitura de diagnóstico — 2026-11-17 (noite), só leituras

RESULTADO REAL, obtido com `get_home_devices` e `get_device_details` (nenhuma escrita):

- **`lastCommunicationTime` é um instante em milissegundos (epoch).** Na leitura, a lâmpada não contactava a cloud há ~14 min e a tomada há ~69 min, com ambas a reportar `power: on`.
- Lâmpada: `workMode: "colour"`, `brightness: 18`, `color_rgb` com `value: "46,31,0"` além dos três canais. O estado difere do registado na verificação física anterior, portanto a cloud aceitou alterações entretanto.
- Tomada: tem `multiPower` com um interruptor `switch_1` (`on`) além de `power`.
- Schema de `update_device_capabilities`: `body` obrigatório; `deviceId`, `deviceName` e `vendor` opcionais. A descrição diz «Update **one** capability» (uma capability por chamada, como o `McpHome` faz) e brilho «0-100», embora o dispositivo declare `min: 1`.
- Latências: abrir sessão ~0,8 s; `get_device_details` 0,65–0,87 s.

### Porque é que a lâmpada pode não ter reagido — hipóteses verificáveis

| # | Hipótese | Evidência | Como confirmar amanhã (ver guia de validação, MCP-04) |
|---|---|---|---|
| H1 | **A lâmpada está sem ligação à cloud**; o MCP aceita a escrita («device updated») mas o dispositivo nunca a recebe | `lastCommunicationTime` com 3 min (verificação) e 14 min (hoje); a releitura voltou ao estado inicial | Ler `lastCommunicationTime` antes e depois de comandar a lâmpada pela app oficial; se não avançar, é conectividade (Wi-Fi 2,4 GHz, alimentação, re-emparelhar) |
| H2 | A escrita é assíncrona e demora mais do que a janela de releitura (~2,5 s + leituras) | Numa tentativa a alteração apareceu ~12 s e reverteu | Após a escrita, ler o estado durante 60 s e ver a lâmpada |
| H3 | `color_rgb` só tem efeito físico em `workMode: colour` | Hoje estava em `colour`; não se sabe em que modo estava na verificação | Registar `workMode` antes de cada teste; o `McpHome` não pode mudá-lo (fora da whitelist e do schema) |
| H4 | O servidor encaminha pelo `vendor`/nome e o `deviceId` sozinho não chega | `vendor` existe no schema («used to decide where to route») | Perguntar aos mentores; não testar às cegas |
| H5 | A tomada é multi-interruptor e `power` não atua em `switch_1` | `multiPower` na leitura | `make mcp-verify what=plug` com carga segura |

Para ajudar a distinguir H1, quando uma escrita não é confirmada o `McpHome` acrescenta ao motivo o tempo sem contacto, por exemplo «estado final não corresponde ao pedido (dispositivo sem contactar a cloud há 14 min)». É só diagnóstico: nunca bloqueia nem repete escritas. **PRESSUPOSTO:** `lastCommunicationTime` reflete o último contacto do dispositivo com a cloud; confirmar com os mentores.

## Limites da evidência

- Leituras de `get_home_devices` e `get_device_details` foram efetuadas. Escritas: ver a
  verificação física acima (sem efeito físico confirmado); a tomada não foi testada.
- A unidade de `instantPower` não consta no schema/resposta observados. Foi confirmada em W por
  medição com carga de referência (ver «Consumo (`instantPower`, #12)»); o consumo em watts só se
  obtém com `MCP_INSTANTPOWER_UNIT=W`.
- `get_home_devices` e `get_device_details` devolvem as mesmas capabilities (comparado em leitura).
  O polling ObjectOS regista separadamente o instante da sua última leitura.
- Latência observada: 1.ª chamada de cada sessão ~2 s, seguintes ~0,5–0,8 s.
