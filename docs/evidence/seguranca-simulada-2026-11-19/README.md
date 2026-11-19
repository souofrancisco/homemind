# Alarme simulado (SAFE-02 #115), 2026-11-19

Browser (Playwright/Chromium), Authentik real em Docker (:19000), backend `DEMO=1` (:18000), frontend (:15173); casa de demonstração SIMULADA. Sem credenciais nas imagens.

| Imagem | O que mostra |
|---|---|
| 01 | Ana (inquilina): proposta «armar» pendente, à espera de confirmação |
| 02 | Após «Confirmar (simulado)»: painel «Armado (simulado)», resultado SIMULADO |
| 03 | Proposta de desarmar cancelada, depois nova proposta confirmada: «Desarmado (simulado)» |
| 04 | Senhorio: Casa sem cartão de alarme; `GET`/`POST …/security` = 403 |
| 05 | Operador: idem (403) |

Todos os pedidos `/api/*` do percurso da Ana foram 2xx; os únicos 4xx foram os 4 pedidos 403 feitos de propósito como senhorio e operador. O estado de presença da demo era `unknown` (a demo não emite ocupação), logo a avaliação mostrada é «sem sinal»; as restantes só em testes.
