# ObjectOS — instruções para Claude Code e outros agentes

**Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs (Connected Home).** Este projeto substitui o conceito antigo de HomeMind Spaces (estadias/hóspedes/turnover). A documentação e issues antigas sobre estadias não são requisitos ObjectOS. Ler `docs/objectos-plano.md` e a issue atribuída antes de implementar.

## Objetivo fechado
Uma câmara MEARI RTSP, ligada em casa própria, observa objetos comuns. Levantar **caneca, livro ou comando** junto ao pulso, com a mão acima do cotovelo durante ~1 s, ativa um modo da casa. Não repetir a ação se o modo já estiver ativo; outro objeto troca o modo. A presença binária mantém o modo; após ausência prolongada desliga luz e tomada, e ao regressar repõe o estado guardado. Há botão manual **desligar tudo**.

Vídeo processado **localmente**, nunca enviado para a NVIDIA/MCP, nem persistido ou registado. Só metadados textuais e eventos. Nada de identificação ou reconhecimento facial. Clip da própria MEARI como reserva.

## Estado real do repositório (não fingir que o plano já está implementado)
- O código existente é um monorepo **em `app/`**, NÃO um diretório `backend/` e `frontend/` na raiz.
- Backend Python **>=3.12** já configurado em `app/backend/pyproject.toml`, FastAPI feature-first em `app/backend/src/homemind/`; `main.py`, `core/config.py`, `core/features.py`, `features/health`, `features/auth`, `features/mcp` já existem.
- O conector `connectors/altice.py` já usa `mcp.ClientSession` + `streamablehttp_client`, e suporta `MCP_ENDPOINT`, `MCP_API_KEY`, `MCP_AUTH_TOKEN` (token externo). **Não comprova OAuth autónomo nem escrita funcional.** Fazer descoberta real e validar esquemas antes de executar ações.
- Frontend `app/frontend/`: React/Vite/TypeScript e **Mantine existente**; auth OIDC, dashboard, Android Capacitor e Docker Compose também existem. Reutilizar componentes do Mantine; não recriar frontend nem autenticação desnecessariamente.
- O README e os AGENTS antigos podem referir Spaces/estadias e testes desativados: **prevalecem este ficheiro, o plano ObjectOS e a issue atual**, quando houver conflito.
- O modelo de dados ObjectOS, regras, máquina de estados, visão, gestos e UI ObjectOS **ainda são tarefas**; não marcar como feito sem código ou demonstração.

## Stack e decisões
- Backend num **único processo** FastAPI/Uvicorn, asyncio, Pydantic v2; visão em thread; `asyncio.Queue` para eventos. Python existente 3.12 serve o requisito 3.11+.
- OpenCV + FFmpeg RTSP/TCP, último frame protegido com lock, reconexão e clip `VIDEO_SOURCE` em loop. JPEG anotado por MJPEG `GET /video`.
- Ultralytics YOLO `yolo11s.pt` para categorias COCO 41 caneca, 73 livro, 65 comando; `yolo11s-pose.pt` para ombros 5/6, cotovelos 7/8 e pulsos 9/10; ByteTrack `track(persist=True)`. GPU CUDA quando disponível; modelos 'n' só se necessário.
- Regra de gesto: centro do objeto a menos de 0,6 × largura dos ombros do pulso, pulso acima do cotovelo, keypoints com confiança >0,5; presente em ≥80% de janela de 1 s; cooldown de 3 s por classe. Ajustáveis via config.
- Presença: desaparece após 3 s sem pessoas; aparece após 2 frames positivos. Sem contar, identificar ou armazenar pessoas.
- `Home` tipado: `definir_lampada(ligada, cor, brilho)`, `definir_tomada(ligada)`, `ler_consumo()`, `estado()`. `FakeHome` primeiro; `McpHome` só após esquemas reais.
- Escritas MCP **apenas para lâmpada e tomada**, pelas tools validadas `GET_HOME_DEVICES`, `GET_DEVICE_DETAILS`, `UPDATE_DEVICE_CAPABILITIES`. Nenhuma ação no alarme/segurança. Descobrir identificadores no arranque; confirmar estado após ação; timeout 5 s, no máximo 1 retry previsto no plano, nunca retry cego se o resultado da escrita for desconhecido.
- NVIDIA somente na **criação/pré-visualização de regras**, não na inferência por frame ou execução. SDK `openai` com base_url `https://integrate.api.nvidia.com/v1`. Saída JSON validada por Pydantic e confirmação humana antes de persistir.
- Persistência simples: `rules.json` e `events.jsonl` (eventos textuais, sem imagens); sem base de dados nova, Redis ou microserviços.
- Estados: Inativo → Ativo → Em espera (180 s; 10 s no perfil demo) → Suspenso; aviso baixar brilho 5 s antes, restaurar ao regressar; abandonar Suspenso após 30 min. Poupança estimada em Wh/EUR baseada em W × horas e tarifa configurada.
- Rotas-alvo: `GET /video`, `WS /ws`, `GET /status`, `GET/POST/DELETE /rules`, `POST /rules/parse`, `POST /off`. **Adicionar na estrutura real existente**, documentar prefixos reais e manter compatibilidade com OpenAPI / `make contracts`.

## Responsabilidades (5 pessoas, sem nomes GitHub assumidos)
| Pessoa | Dono / local preferido |
|---|---|
| 1 | Vídeo, visão, MJPEG, integração/demo; novas features ou módulos ObjectOS em `app/backend/src/homemind/` |
| 2 | Gestos, presença, afinador offline e publicação de eventos |
| 3 | Interface Home, FakeHome, MCP real, descoberta, verificação e segurança de capacidades; adaptar `connectors/altice.py` |
| 4 | Contratos acordados, motor de regras e estados, energia, eventos, LLM, testes |
| 5 | Frontend `app/frontend/src/`: websocket, vídeo, estado, eventos, regras, controlo, acessibilidade |

Os contratos partilhados são definidos primeiro em conjunto; não alterar assinaturas de `Home`, eventos ou modelos sem coordenação. Não editar ficheiros de outra pessoa sem acordo. Uma issue por branch/worktree; PRs pequenos para trabalho normal. O pedido específico de reorganização da documentação autoriza commit direto na `main`; **não autoriza agentes futuros a fazerem push direto sem instruções**.

## Segurança e privacidade
- `MCP_ENDPOINT`, `MCP_API_KEY`, tokens OAuth e `NVIDIA_API_KEY` apenas em configuração local ignorada pelo Git. Nunca expor em logs, erros, prints, issues ou docs.
- Preservar `ENABLE_PHYSICAL_WRITES=false` por omissão no legado; FakeHome para desenvolvimento e demo offline. Escritas só com consentimento operacional, dispositivos permitidos, chamada verificada e possibilidade de desligar tudo.
- RTSP e imagens apenas locais. Não chamar cloud com vídeo, frames, descrições privadas de pessoas ou histórico bruto. Não guardar frames. O ficheiro de vídeo de reserva é material de demo gravado explicitamente com consentimento, fora dos logs e do Git se contiver pessoas.
- Nunca inventar o resultado de `tools/list`, capacidades, IDs, leituras ou ações reais. Distinguir SIMULADO de REAL em UI e pitch.

## Organização, testes e critérios de feito
- Ler `docs/objectos-plano.md` e a issue; implementar só o pedido, sem extras prematuros. A fase MVP tem prioridade sobre os extras.
- Conservar o layout real: `app/backend/src/homemind/` e `app/frontend/src/`; seguir os padrões de `core/features.py` e Mantine. `config.py` centraliza limiares/tempos/URLs/modelos.
- `make check` para lint, contrato OpenAPI e build; correr `pytest` para a máquina de estados e lógica pura com FakeHome/fixtures simuladas (nunca depender de hardware, rede ou NVIDIA). A regra antiga 'não criar testes' fica ultrapassada para estas tarefas exigidas pelo plano.
- Não acrescentar dependências sem necessidade: OpenCV, Ultralytics e SDK OpenAI não estão no `pyproject.toml` atual; adicioná-los só nas issues correspondentes e atualizar lockfiles.
- Critérios da demo: vídeo com atraso <1,5 s durante 10 min, inferência ≥10 FPS se GPU disponível, gesto → luz <4 s, 10 gestos corretos sem falsos positivos e **10 demos completas seguidas**. Documentar limites quando hardware não permitir.
- Entregáveis: resumo executivo PDF 2 páginas até **18/11/2026 19h00**, PPT e pitch 3 min/5 min, README atualizado e plano B com clip.
- Extras (sugestões de rotinas, editor completo, brilho por gesto, treino de objeto, cenários MCP) **apenas após MVP estável e pedido explícito**.
