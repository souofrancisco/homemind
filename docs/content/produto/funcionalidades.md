# Funcionalidades

Estado de cada funcionalidade, sem misturar o que existe com o que está desenhado. Evidência por fluxo em [Funcionalidades verificadas](../demo/verificado.md).

| Funcionalidade | Estado | Nota |
|---|---|---|
| Login Authentik (OIDC + PKCE) com papéis morador, senhorio e operador | <span class="estado estado--ok">IMPLEMENTADO</span> | Visto no browser; contas só no Authentik local |
| Casa, quartos e zonas comuns | <span class="estado estado--ok">IMPLEMENTADO</span> | Dados de demonstração simulados |
| Consumo por tomada com proveniência (medido / estimado / simulado) | <span class="estado estado--ok">IMPLEMENTADO</span> | Sem coletor em runtime com FakeHome |
| Pergunta «De quem é esta conta?» com votação dos moradores | <span class="estado estado--ok">IMPLEMENTADO</span> | Browser só para «É minha»; restantes respostas só em testes |
| Fatura do senhorio: pré-visualizar, registar, finalizar | <span class="estado estado--ok">IMPLEMENTADO</span> | Visto no browser |
| Repartição quarto / comum / resíduo; recibos que somam a fatura | <span class="estado estado--ok">IMPLEMENTADO</span> | 4 recibos somam 120,00 € |
| Recibo explicado («Porque pago isto?») | <span class="estado estado--ok">IMPLEMENTADO</span> | Visto no browser |
| Orçamento mensal com avisos a 50/80/100 % | <span class="estado estado--ok">IMPLEMENTADO</span> | Previsão mensal e tarifário não existem |
| Consentimento por fonte de presença, retenção e exportação | <span class="estado estado--ok">IMPLEMENTADO</span> | Pistas injetadas à mão; prazos são PROPOSTA |
| Alarme simulado: armar/desarmar com confirmação | <span class="estado estado--ok">IMPLEMENTADO</span> | Simulado; leitura MCP real só de leitura |
| Regras da casa votadas | <span class="estado estado--ok">IMPLEMENTADO</span> | Motor simulado; sem executor físico |
| Estimativa da lâmpada (9 W × tempo × brilho) | <span class="estado estado--ok">IMPLEMENTADO</span> | Só testes; sem hardware |
| Limite mensal de 5 kWh antes de perguntar | <span class="estado estado--prop">PROPOSTA</span> | Implementada, por validar com a equipa |
| Interface do assistente de IA | <span class="estado estado--plan">PLANEADO</span> | Há backend e histórico; a página é um placeholder |
| Hardware real (MCP) validado ponta a ponta | <span class="estado estado--plan">PLANEADO</span> | Nunca validado |
| Opção C da sala por presença | <span class="estado estado--plan">PLANEADO</span> | Não implementada |
| Previsão mensal e tarifário | <span class="estado estado--plan">PLANEADO</span> | |
| Push e acesso offline | <span class="estado estado--plan">PLANEADO</span> | |
| Telegram/bots, HAN/E-REDES, reconhecimento facial, gravação de vídeo, MEO Energia, multi-imóvel | Fora do MVP | Só com pedido explícito |

## Regras de domínio principais

- **Dinheiro:** repartição determinística em código, arredondamentos explícitos, fecho reconciliado a 100 % da fatura. O recibo distingue medido, estimado e simulado e é contestável. O senhorio só reparte o custo real da fatura.
- **Plafond solidário** (opcional, por quarto, definido pelo senhorio; 0 = sem plafond): o aquecimento básico é pago em comum e só o excesso é individual.
- **Atribuição por aparelho, não por tomada.** Sem identificação nem evidência, divide-se por igual ou só por quem estava em casa. O assistente só pergunta quando vale a pena.
- **Votação «De quem é esta conta?»:** um «É minha» basta; atribuir a outra pessoa exige pelo menos metade dos moradores; inconclusivo em 24 h, divide-se por todos.
- **Alertas:** orçamento a 50/80/100 % com previsão; pico = zona comum acima de 1,5 kW durante mais de 30 min.
- **Assistente de IA:** nunca inventa números; tudo vem de ferramentas tipadas, as contas fazem-se em código e as ações sensíveis pedem confirmação humana.

*Fontes canónicas: `docs/functional-flows.md`, `docs/product/requirements.md`.*
