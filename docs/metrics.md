# KPIs
**Metas internas (não são resultados):**
| Meta | Alvo | Medido |
|---|---|---|
| Primeira leitura MCP real | 16/11 | — |
| Percurso completo de 2 estadias | 17/11 | — |
| CI verde em `main` | sempre | — |
| Demos completas seguidas sem falhas | 3 | — |
| Check-in+check-out do gestor | < 1 min de cliques | — |
| Entregáveis: relatório 18/11 19h00; sumário+PPT 20/11 17h30 | submetidos | — |
Resultados medidos: preencher só com evidência. Sem poupanças inventadas.

## ObjectOS — vídeo (issue #2)

Medido em 17/11/2026 com `python -m homemind.features.video.medir --minutos 10`, câmara MEARI através do relay RTSP (não em rede local), stream principal.

| Medida | Alvo | Medido |
|---|---|---|
| Duração da leitura contínua | 10 min | 600 s, 5974 frames |
| FPS da fonte | — | 10,0 (estável minuto a minuto) |
| Maior intervalo entre frames | — | 609 ms (420–610 ms em todos os minutos) |
| Quedas de `camara_ok` | 0 | 0 |
| Resolução | — | 1920x1080 |
| Atraso câmara→ecrã em `GET /video` | < 1,5 s | por medir (cronómetro) |
| Stream secundário | comparar | por medir (sem URL) |
