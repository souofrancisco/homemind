# Modelos e contratos

Os contratos (`contracts/`: modelos partilhados, eventos de domínio e modelos da API) mudam **juntos e só com acordo da equipa**. Tarefas que lhes tocam não correm em paralelo. O frontend usa os tipos gerados do OpenAPI e nunca os redefine.

## Modelo de dados

- Dinheiro em cêntimos; energia em Wh; ausência = `None`.
- Proveniência em tudo o que é medido ou calculado: `measured`, `estimated`, `inferred`, `simulated`.
- Papéis: `Membership.role` (`landlord`, `tenant`, `operator`).

## Eventos de domínio

Persistidos em SQLite, imutáveis, consumidores idempotentes por id, sem imagens nem identificadores externos no payload. As features comunicam apenas por eventos e contratos.

## API REST

<span class="estado estado--ok">IMPLEMENTADO</span> O OpenAPI gerado pelo backend é a fonte exata das rotas e dos esquemas. Em `/docs` (Swagger) com o backend a correr.

Grupos de rotas ativas, todas `/api/*` com Bearer Authentik (exceto `GET /healthz`):

- identidade e convites;
- casas, divisões, membros, aparelhos e dispositivos;
- energia e faturação: leituras, consumo, assinaturas, tarifas, orçamentos, faturas, recibos, revisões e contestações;
- presença: estado próprio, ocupação autorizada, exportação e estado da câmara (a API não devolve imagens);
- notificações e assistente;
- diagnóstico MCP.

O WebSocket de notificações é <span class="estado estado--plan">PLANEADO</span>; não há endpoint ativo.

*Fontes canónicas: `docs/architecture/contracts.md`, `docs/architecture/data-model.md`, `docs/architecture/api-implementada.md`.*
