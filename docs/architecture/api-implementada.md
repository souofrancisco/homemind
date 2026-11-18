# API implementada — Conta Certa

> O OpenAPI gerado pelo backend é a fonte exata das rotas e esquemas atuais. A API antiga foi
> removida na BASE-04 (#74); o registo da migração está em [migration.md](migration.md).

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

O WebSocket de notificações permanece **PLANEADO** em [contracts.md](contracts.md), sem endpoint
ativo.

`GET /api/video` está registado pela feature de vídeo; a resposta e os controlos de PRIV-02 são
descritos em [presence.md](../modules/presence.md) e no código.
