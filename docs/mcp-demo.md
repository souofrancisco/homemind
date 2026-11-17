# ObjectOS com MCP Altice — operação e demo

Fluxo: câmara → gesto → evento → regra → motor → `McpHome` → MCP Altice → dispositivo → releitura →
`home_state` (REST/WS) → frontend. O frontend não muda: fala com o mesmo backend; só muda
`HOME_BACKEND=mcp`.

## 1. Configuração (`app/.env`, a partir de `app/.env.example`)

`MCP_ENDPOINT`, `MCP_API_KEY`, `MCP_CLIENT_TYPE`, `MCP_OAUTH_*`. Nunca commitar o `.env`.

## 2. Login OAuth (só no host, interativo)

```bash
make mcp-login      # abre o browser; guarda tokens em app/.mcp-auth/tokens.json (dir 0700, ficheiro 0600)
make mcp-doctor     # initialize + tools/list no MCP real; não escreve nada
```

O backend nunca abre browser: com sessão expirada/revogada fica `mcp_ok=false` com o aviso
«Sessão OAuth MCP expirada; execute make mcp-login no host». O access token renova sozinho; no backend há uma única sessão MCP (todas as chamadas, incluindo
`/api/mcp/tools`, passam por ela) e o ficheiro de tokens é protegido por `flock` entre host e container. Os tokens vivem numa
**diretoria** montada no container (o `os.replace` atómico falha com bind mount de um ficheiro);
o utilizador `app` do container é uid 1000 — a diretoria tem de ser desse uid.

## 3. Arrancar em modo MCP read-only

```bash
HOME_BACKEND=mcp make mcp-up          # backend isolado em :18080 (sem frontend)
make mcp-demo                         # demo completa: frontend + Authentik + backend (HOME_BACKEND=mcp)
make mcp-down | make mcp-demo-down
```

Com `ENABLE_PHYSICAL_WRITES=false` (omissão) nenhuma escrita é feita; leituras a cada 5 s.
`POST /api/simulate` responde 403 com `HOME_BACKEND=mcp`. Para a demo completa a câmara usa
`VIDEO_SOURCE` e `VISAO_DETETOR` do `.env`, como em `make dev`.

## 4. Autorizar escritas físicas (temporário)

Duas chaves, ambas necessárias: `ENABLE_PHYSICAL_WRITES=true` no `.env` (recriar o container) **e**
um grant temporário criado por quem tem shell no host. Não existe endpoint HTTP de ativação.

```bash
make mcp-writes-on minutes=15              # lâmpada + tomada, máx. MCP_WRITE_MAX_MINUTES (60)
make mcp-writes-on minutes=15 roles=lamp   # só a lâmpada
make mcp-writes-status
make mcp-writes-off                        # revoga de imediato
# demo completa: acrescentar stack=demo
```

O grant é um ficheiro 0600 no volume de dados, lido em cada escrita: expira sozinho, apagar revoga.
O motor (regras, temporizadores, «Desligar tudo») usa o mesmo `McpHome`, por isso funciona
enquanto o grant estiver ativo e é recusado logo depois. A whitelist (3 ferramentas exatas;
lâmpada `power|brightness|color_rgb`, tomada `power`) é independente e nunca se relaxa.

## 5. Verificação física controlada (#10/#11)

```bash
make mcp-verify what=lamp   # mostra a alteração, exige escrever «AUTORIZO LAMPADA», relê, restaura
make mcp-verify what=plug   # só com carga segura ligada; exige «AUTORIZO TOMADA»
```

## 6. Voltar a FakeHome

`HOME_BACKEND=fake` (omissão) e `docker compose -f app/compose.yaml up`. `/api/simulate` volta a
funcionar. O FakeHome é independente do MCP.

## 7. Interpretar estados e erros

| Sinal | Significado |
| --- | --- |
| `mcp_ok=false` | última leitura MCP falhou; lâmpada/tomada ficam `null` (desconhecido), consumo `null`; recupera sozinho |
| `casa.aviso` «Sessão OAuth MCP expirada…» | `make mcp-login` no host |
| `casa.aviso` «Unidade de instantPower não declarada…» | consumo em W desconhecido (ver #12); `consumo_w=null` |
| `casa.aviso` «…inequivocamente…» | 0 ou vários candidatos; definir `MCP_LAMP_ID`/`MCP_PLUG_ID` |
| evento «Falha ao atuar em … : escritas físicas desativadas» | flag a false |
| evento «… sem sessão de escritas autorizada» | grant ausente/expirado: `make mcp-writes-on` |
| evento «… estado final não corresponde ao pedido» | releitura difere do pedido; nada foi dado como sucesso |
| `/api/off` com `partial_failure` / `mcp_unavailable` | um / nenhum dispositivo confirmado desligado (a mensagem diz porquê) |
| `ligada: null` | `power` devolvido ≠ `on`/`off`: desconhecido |

Escritas de resultado incerto (timeout) nunca são repetidas: só se relê (até 5 releituras, 0,5 s,
porque a cloud pode demorar a refletir o estado). Um gesto com falha física
não ativa o modo nem contabiliza poupança.

## 8. Latência (medida no MCP real)

O servidor demora ~2 s na 1.ª chamada de cada sessão e ~0,5–0,8 s nas seguintes. O `McpHome`
mantém uma sessão persistente (aberta por uma tarefa dona), cacheia catálogo validado e IDs, e faz a
escrita e a releitura na mesma sessão. Leitura de ambos os dispositivos em sessão quente: ~0,9 s
(antes ~3 s). Os tempos ficam em `McpHome.tempos_ms` e no log (`escrita MCP lamp: ok em N ms`).
