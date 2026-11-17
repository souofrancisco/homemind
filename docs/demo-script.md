# Guião da demo

Só se mostra como REAL o que foi validado em `guia-validacao-manual.md`. Tudo o resto é dito em voz alta como **simulado**. Checklist de preparação em `estado-para-amanha.md`.

## Antes de entrar (10 min)

1. `PROFILE=demo` em `app/.env`; servidor arrancado de fresco; painel aberto na página **Início** e sessão iniciada.
2. Câmara enquadrada, objetos na mesa (caneca, livro, comando), luz ambiente estável.
3. Modo MCP: `make mcp-doctor` verde, `make mcp-writes-on stack=demo minutes=30`, lâmpada visível para a audiência.
4. Plano B pronto noutra consola (ver abaixo). Portátil ligado à corrente, notificações desligadas.

## Guião (3 min)

| Tempo | Ação | O que a audiência vê | O que dizer |
|---|---|---|---|
| 0:00 | Entrar em cena | Presença «alguém na divisão»; vídeo com esqueleto | «A casa vê que cheguei. O vídeo nunca sai deste portátil.» |
| 0:20 | Levantar a **caneca** | Modo pausa; luz quente a 30 % | «Não usei app nem voz. Usei a caneca.» |
| 0:45 | Levantar o **livro** | Modo leitura; luz a 40 %, tomada ligada | «Outro objeto, outro modo. Repetir o mesmo não faz nada.» |
| 1:10 | Sair de cena | Em espera com contagem; luz baixa a 20 %; Suspenso | «Divisão vazia: avisa, depois desliga luz e tomada.» |
| 1:40 | Regressar | Estado anterior restaurado; poupança estimada | «Volto e está como deixei. Aqui a estimativa do que poupou.» |
| 2:00 | Criar regra por texto | Proposta, resumo, confirmação | «A IA só propõe. Eu confirmo. Nunca vê o vídeo.» |
| 2:30 | **Desligar tudo** | Tudo desligado, estado Inativo | «E há sempre um botão.» |
| 2:45 | Fecho | Registo de eventos em texto | «Sem gravações, sem rostos: só este texto.» |

## Planos B (dizer sempre que é simulação)

| Falha | Ação |
|---|---|
| Câmara ou rede RTSP | `VIDEO_SOURCE=<clip MEARI>` e reiniciar o backend |
| Visão ou gestos instáveis | Página **Câmara → Cenários de demonstração** (eventos marcados `[SIMULADO]`), só com `HOME_BACKEND=fake` |
| MCP ou lâmpada sem reagir | `HOME_BACKEND=fake` e reiniciar; o painel mostra SIMULADO. Mostrar as leituras reais do MCP à parte (`make mcp-doctor`) |
| NVIDIA indisponível | Saltar o passo 2:00; as regras predefinidas funcionam |
| Login falha | Sessão já iniciada antes de entrar; não fechar o separador |

## Não dizer

- «Controlamos a lâmpada real» sem o teste MCP-04 ter passado nesse dia.
- Valores de poupança como medições: são estimativas.
- Latências ou taxas de acerto que não estejam em `metrics.md`.
