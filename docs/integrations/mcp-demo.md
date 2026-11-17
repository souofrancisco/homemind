# ObjectOS com MCP Altice — operação e demo

> **Nota (Conta Certa):** documento operacional do MCP herdado do ObjectOS, **mantido sem perda**. Onde fala em «gesto», «motor» e «modos», é o produto antigo; as secções de OAuth, escritas autorizadas, erros e latência continuam válidas. Ponto de entrada: [altice-mcp.md](altice-mcp.md).

Fluxo: câmara → gesto → evento → regra → motor → `McpHome` → MCP Altice → dispositivo → releitura →
`home_state` (REST/WS) → frontend. O frontend não muda: fala com o mesmo backend; só muda
`HOME_BACKEND=mcp`.

## 1. Configuração (`app/.env`, a partir de `app/.env.example`)

`MCP_ENDPOINT`, `MCP_API_KEY`, `MCP_CLIENT_TYPE`, `MCP_OAUTH_*`. Nunca commitar o `.env`.

`MCP_INSTANTPOWER_UNIT` (`W`, `dW` = 0,1 W ou `mW`). O MCP não declara a unidade de
`instantPower`; sem esta variável `consumo_w` fica `null`. No kit real a unidade foi confirmada em
**W** por medição com carga de referência (#12, ver [mcp-capabilities.md](mcp-capabilities.md)): usar
`MCP_INSTANTPOWER_UNIT=W` para ter `consumo_w`. Com outro kit, confirmar de novo antes de definir.

## 2. Login OAuth (só no host, interativo)

```bash
make mcp-login      # abre o browser; guarda tokens em app/.mcp-auth/tokens.json (dir 0700, ficheiro 0600)
make mcp-doctor     # só leitura: tools/list + estado e último contacto da lâmpada/tomada (sem IDs)
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

Ciclo rápido (nunca reinicia Authentik; Python e React recarregam sozinhos pelos bind mounts):

```bash
make mcp-demo-reload  # restart só de backend+frontend (Authentik/Postgres intactos)
make mcp-demo-build   # rebuild só de backend+frontend (após mudar dependências/Dockerfile)
make mcp-demo-logs    # logs de backend+frontend
make mcp-demo-check   # diagnóstico: rede/DNS, proxy, REST, WS, modo MCP (só leitura)
make mcp-demo-down    # paragem (sem -v: volumes e tokens preservados)
```

**502 em `/api/*`:** se a porta 8000 estiver ocupada no arranque, o Docker falha a ligar o backend à rede
mas o container fica a correr e `healthy` (o healthcheck é interno). O frontend não o resolve (DNS) → 502.
`make mcp-demo` deteta e recria só o backend; `make mcp-demo-check` mostra o diagnóstico. Libertar a
porta com `BACKEND_PORT=<outra> make mcp-demo`. Um `401` em `/api/*` sem token é normal (a API respondeu).

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
| `mcp_ok=false` | duas leituras seguidas falharam (a 1.ª falha repete-se logo numa sessão nova); lâmpada/tomada ficam `null` (desconhecido), consumo `null`; recupera sozinho. Também após uma escrita enviada cuja releitura falhou |
| `casa.aviso` «Sessão OAuth MCP expirada…» | `make mcp-login` no host |
| `casa.aviso` «Unidade de instantPower não declarada…» | consumo em W desconhecido (ver #12); `consumo_w=null`; definir `MCP_INSTANTPOWER_UNIT` depois de confirmar a unidade |
| `casa.aviso` «…inequivocamente…» | 0 ou vários candidatos; definir `MCP_LAMP_ID`/`MCP_PLUG_ID` |
| evento «Falha ao atuar em … : escritas físicas desativadas» | flag a false |
| evento «… sem sessão de escritas autorizada» | grant ausente/expirado: `make mcp-writes-on` |
| evento «… estado final não corresponde ao pedido» | releitura difere do pedido; nada foi dado como sucesso |
| evento «… (dispositivo sem contactar a cloud há N min)» | o MCP aceitou a escrita mas o dispositivo parece offline; ver hipóteses em `mcp-capabilities.md` |
| `/api/off` com `partial_failure` / `mcp_unavailable` | um / nenhum dispositivo confirmado desligado (a mensagem diz porquê) |
| `ligada: null` | `power` devolvido ≠ `on`/`off`: desconhecido |

Escritas de resultado incerto (timeout) nunca são repetidas: só se relê (até 5 releituras, 0,5 s,
porque a cloud pode demorar a refletir o estado). Um gesto com falha física
não ativa o modo nem contabiliza poupança.

## 8. Tokens partilhados entre host e container

O ficheiro de tokens é único (`app/.mcp-auth/tokens.json`). `make mcp-doctor` e `make mcp-verify` no host podem renovar o token enquanto o backend corre. Se o servidor rodar o refresh token, o backend pode mostrar durante um ciclo de polling o aviso de sessão expirada; a sessão seguinte relê o ficheiro e recupera sozinha. Se o aviso persistir mais de 15 s: `make mcp-login`.

Timeouts do `McpHome`: abrir sessão 10 s, leitura 8 s, escrita com releituras 14 s.

## 9. Latência (medida no MCP real)

O servidor demora ~2 s na 1.ª chamada de cada sessão e ~0,5–0,8 s nas seguintes. O `McpHome`
mantém uma sessão persistente (aberta por uma tarefa dona), cacheia catálogo validado e IDs, e faz a
escrita e a releitura na mesma sessão. Leitura de ambos os dispositivos em sessão quente: ~0,9 s
(antes ~3 s). Os tempos ficam em `McpHome.tempos_ms` e no log (`escrita MCP lamp: ok em N ms`).

**Medição por refazer.** Os tempos acima foram medidos com o transporte a enviar cada pedido MCP
duas vezes (o SDK `mcp` 1.12.4 reenvia sempre o pedido autenticado; correção em
`connectors/altice_auth.py`). Com um pedido por chamada as latências devem baixar: voltar a medir
no kit real e atualizar esta secção.

**Pior caso com o MCP pendurado.** Uma escrita espera pelo lock do polling e depois pelo seu
próprio timeout: no pior caso ~22 s até devolver falha (por exemplo `/api/off` com o MCP
pendurado). É aceitável para a demo: a resposta é sempre `success: false`/`mcp_unavailable` e nunca
um estado inventado. O polling repete uma leitura falhada uma vez, o que também pode ocupar o lock
até ~2× o timeout de leitura quando o servidor está em baixo.

**Pedido ao motor (P4, ainda não implementado).** Se uma leitura falhada deixar `lampada.ligada`
a `None` no instante em que a pessoa sai, o motor guarda estado desconhecido e não repõe a luz ao
regressar. Proposta: em `engine.py`, reaplicar `self.modo.acoes` ao regressar quando
`_guardado.lampada.ligada is None`.
