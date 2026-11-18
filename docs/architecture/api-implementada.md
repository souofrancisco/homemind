# API implementada — Conta Certa

> **Estado após BASE-04 (#74):** a API do motor ObjectOS foi **REMOVIDA**. Este documento descreve
> a aplicação atual; o OpenAPI gerado pelo backend é a fonte exata de rotas e esquemas.

## API ativa

`GET /healthz` é público. As restantes rotas `/api/*` usam Bearer Authentik, salvo indicação
específica no contrato de cada feature.

- Identidade: `/api/me`, `/api/me/context`, convites.
- Casa e operação: casas, divisões, membros, aparelhos e dispositivos por casa.
- Energia e faturação: leituras, consumo, assinaturas, tarifas, orçamentos, faturas, recibos,
  revisões e contestações.
- Presença: estado próprio, ocupação autorizada, dispositivos registados, exportação e estado da
  câmara. A API não devolve imagens.
- Notificações e assistente: notificações e preferências por casa; mensagens e ações do assistente.
- MCP: `GET /api/mcp/tools` para diagnóstico.

Os caminhos, DTOs e permissões atuais estão declarados nas rotas e nos contratos Pydantic. Consulte
`app.openapi()` ou execute `python -m homemind.openapi` para gerar o documento OpenAPI.

## API do motor ObjectOS — REMOVIDA (BASE-04)

As rotas abaixo já não estão registadas nem aparecem no OpenAPI:

| Rota/protocolo removido | Função antiga |
|---|---|
| `GET /api/status`, `GET /api/state`, `GET /api/events` | Estado da casa e log do motor |
| `GET/POST/PATCH/DELETE /api/rules*`, `POST /api/rules/parse` | Regras ObjectOS e propostas NVIDIA |
| `POST /api/off`, `POST /api/simulate` | Desligar tudo e injetar eventos de demonstração |
| `WS /api/ws` | Snapshot `home_state` e eventos do motor |

Os nomes de regras, eventos e estado que ainda aparecem em tipos antigos do frontend são legado;
este backend não fornece esses caminhos. O WebSocket de notificações permanece **PLANEADO** em
[contracts.md](contracts.md), sem endpoint ativo.

`GET /api/video` está registado pela feature de vídeo; a resposta e os controlos de PRIV-02 são
descritos em [presence.md](../modules/presence.md) e no código.
