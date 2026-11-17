# Perguntas aos mentores (Altice)

> Perguntas ainda abertas aos mentores Altice. A pergunta 6 (unidade de `instantPower`) e as 1–2 e 7 (escritas) são **bloqueios da Conta Certa**. Ponto de entrada: [altice-mcp.md](altice-mcp.md).

Registar a resposta e a data por baixo de cada pergunta. Contexto técnico em [mcp-capabilities.md](mcp-capabilities.md).

1. **Lâmpada não reage.** `update_device_capabilities` devolve «device updated» mas a lâmpada não muda e a releitura volta ao estado inicial. O `lastCommunicationTime` da lâmpada tinha 3 a 14 min. A lâmpada está online na cloud? É preciso re-emparelhar ou outra rede Wi-Fi? —
2. **A escrita é assíncrona?** Quanto tempo pode passar entre o «device updated» e o efeito físico? Há forma de saber que o comando chegou ao dispositivo? —
3. **`lastCommunicationTime`** representa o último contacto do dispositivo com a cloud? Com que frequência é atualizado num dispositivo saudável? —
4. **`workMode`**: `color_rgb` e `brightness` só têm efeito em `colour`? Como se muda o modo pelo MCP (não está no schema de escrita)? —
5. **`vendor` / `deviceName`**: é preciso enviar `vendor` além do `deviceId` para o comando ser encaminhado? —
6. **Unidades**: `instantPower`, `instantVoltage`, `instantCurrent` (máximos 50000 / 50000 / 30000) estão em W, 0,1 W ou mW? `todayConsumption` é kWh? —
7. **Tomada**: tem `multiPower` com `switch_1`. O `power` de topo controla esse interruptor? —
8. **Brilho**: o schema diz 0–100 e o dispositivo `min: 1`. O valor 0 desliga? —
9. **Limites**: há rate limit ou número máximo de sessões OAuth por equipa? O refresh token roda a cada renovação? —
10. **Avaliação**: o que valorizam mais — controlo físico ao vivo, robustez, privacidade, replicabilidade? Um plano B simulado, claramente identificado, é aceitável na demo? —
