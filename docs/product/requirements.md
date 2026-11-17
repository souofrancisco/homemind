# Requisitos

Todos **PLANEADO** (nada disto existe ainda no código, salvo indicação). Origem: **PDF §x** = proposta original; **DECISÃO** = decidido nesta reorganização ([decisions.md](../decisions.md)); **PROPOSTA** = ideia nossa por validar. Prioridades: P0 = MVP obrigatório, P1 = segue o MVP, P2 = posterior. Detalhe de entregas por pessoa em [development/team.md](../development/team.md).

## Casa Justa

| ID | Requisito | Origem | Prio | Dono |
|---|---|---|---|---|
| RF-01 | Registar casa, quartos, moradores e a ligação pessoa–quarto | PDF §6.8, §10.3 | P0 | P5 |
| RF-02 | Registar aparelhos (pessoais, partilhados, comuns) com dono e potência típica | PDF §6.4 | P0 | P1 |
| RF-03 | Recolher leituras de potência da tomada com proveniência | PDF §16–17 | P0 | P1 |
| RF-04 | Detetar degraus de potência | PDF §6.3 | P0 | P1 |
| RF-05 | Identificar o aparelho por assinatura, com confiança; abaixo do limiar → desconhecido | PDF §6.3, §9 (M2) | P0 | P1 |
| RF-06 | Localizar o consumo (quarto ou zona comum). **MVP:** pela zona registada do aparelho e pela tomada principal, não por tomadas de quarto | PDF §6.3, adaptado | P0 | P1 |
| RF-07 | Pedir confirmação na aplicação («É minha / É de todos / Não sei») com ações na notificação | DECISÃO (substitui Telegram) | P0 | P3 |
| RF-08 | Persistir a resposta e recalcular a atribuição segundo as regras da casa | DECISÃO | P0 | P4 |
| RF-09 | Regras da conta da sala: A (por igual), B (perguntar), fallback sem resposta em 24 h | PDF §6.2 | P0 | P4 |
| RF-10 | Regra C (por quem está em casa) | PDF §6.2 | P1 | P4 |
| RF-11 | Limiar de custo para perguntar (ex.: 0,50 €; abaixo vai para a conta comum) | PDF §6.2 (valor «por exemplo») | P1 | P4 |
| RF-12 | Decompor a fatura: parte fixa, consumo individual, resíduo | PDF §7 | P0 | P4 |
| RF-13 | Entrada manual da fatura (total, parte fixa, preço, kWh) | PROPOSTA | P0 | P4 |
| RF-14 | Ler a fatura por LLM multimodal (foto/PDF) | PDF §9 (M6) | P2 | P3 |
| RF-15 | Recibo individual explicado, com o que é medido e o que é estimado | PDF §6, §11.1 | P0 | P4 |
| RF-16 | Contestar um consumo ou um recibo | PDF §2.1, §11.1 | P1 | P4 + P3 |
| RF-17 | Plafond solidário por quarto | PDF §7 | P1 | P4 |
| RF-18 | Valorização bi-horária | PDF §7 | P2 | P4 |
| RF-19 | Aprendizagem a partir das confirmações (melhorar assinaturas) | PDF §6.3 passo 6 | P1 | P1 |
| RF-19b | Agrupar aparelhos desconhecidos (clustering) | PDF §6.6 | P2 | P1 |

## Casa Atenta

| ID | Requisito | Origem | Prio | Dono |
|---|---|---|---|---|
| RA-01 | Orçamento pessoal com avisos a 50 %, 80 % e 100 % | PDF §6.9 | P0 | P4 |
| RA-02 | Previsão do fim do mês (projeção linear simples) | PDF §6.9, §9 (M4) | P1 | P4 |
| RA-03 | Plafond do senhorio por quarto, com aviso antes e depois | PDF §6.9 | P1 | P4 |
| RA-04 | Pico em zona comum (ex.: > 1,5 kW durante > 30 min) | PDF §6.9 | P1 | P4 |
| RA-05 | Aparelho esquecido (dono fora há > 1 h) — depende de presença | PDF §6.9 | P2 | P4 + P2 |
| RA-06 | «Não bate certo» (assinatura fora do quarto do dono, consumo noturno anormal) | PDF §6.9, §8 | P2 | P4 |
| RA-07 | Recomendações e anomalias (desvio ao perfil habitual) | PDF §9 (M5) | P2 | P4 |
| RA-08 | Lâmpada RGB como feedback (verde/âmbar/vermelho) | PDF §4 | P2 | P1 |

## Casa Segura

| ID | Requisito | Origem | Prio | Dono |
|---|---|---|---|---|
| RS-01 | Contar entradas e saídas na porta (pessoa + linha na soleira), só eventos | PDF §5 | P1 | P2 |
| RS-02 | Máscara de privacidade: só a soleira é analisada; sem gravação | PDF §5.3, CLAUDE.md | P0 (restrição) | P2 |
| RS-03 | Presença por pessoa «em casa / fora / incerto» por fusão de pistas | PDF §6.8 | P1 | P2 |
| RS-04 | Registo manual «cheguei / saí» na aplicação | PROPOSTA (substitui o botão do bot; PDF §20 #7) | P0 | P2 + P3 |
| RS-05 | Presença por Wi-Fi com opt-in | PDF §10.2 | P2 | P2 |
| RS-06 | Estado «casa vazia» | PDF §5.1 | P2 | P2 |
| RS-07 | Alerta de entrada com a casa vazia | PDF §5.1 | P2 | P2 + P3 |
| RS-08 | Automação autorizada (ex.: janela aberta + aquecedor → corte da tomada) | PDF §3, §12 | P2 | P1 + P3 |
| RS-09 | Armar alarme / segurança do Connected Home | PDF §3.1 | **Fora de âmbito** até decisão ([decisions.md](../decisions.md) P-01) | — |

## Notificações e aplicação

| ID | Requisito | Origem | Prio | Dono |
|---|---|---|---|---|
| RN-01 | Centro de notificações integrado | DECISÃO | P0 | P3 (UI: P5) |
| RN-02 | Notificações pessoais e da casa | DECISÃO (substitui privado/grupo do bot; PDF §6.9) | P0 | P3 |
| RN-03 | Notificações interativas com ações; resposta persistida | DECISÃO | P0 | P3 |
| RN-04 | Alertas de consumo e de orçamento | DECISÃO | P0 | P4 + P3 |
| RN-05 | Histórico de notificações | DECISÃO | P1 | P3 |
| RN-06 | Preferências (limiares, silêncio noturno) | DECISÃO; PDF §6.9 | P1 | P3 |
| RN-07 | Entrega em tempo real na aplicação (WebSocket) | DECISÃO | P0 | P3 + P5 |
| RN-08 | Notificações push (Capacitor) | DECISÃO («no futuro, quando viável») | P2 | P3 + P5 |
| RN-09 | Votação de regras e da câmara pela casa, na aplicação | PDF §5.3, §12 | P2 | P3 |

## Assistente de IA

| ID | Requisito | Origem | Prio | Dono |
|---|---|---|---|---|
| RI-01 | Guarda-corpo: nenhum número vem do modelo; tudo de ferramentas; contas em código | PDF §9 | P0 (restrição) | P3 |
| RI-02 | Assistente integrado na aplicação | DECISÃO | P1 | P3 (UI: P5) |
| RI-03 | Explicar recibos («porque pago mais?») | PDF §12 | P1 | P3 |
| RI-04 | Ações sugeridas, com confirmação antes de executar | DECISÃO | P2 | P3 |
| RI-05 | Regras escritas em português → automação (reutiliza `features/engine/llm.py`) | PDF §12; código existente | P2 | P3 |

## Privacidade e operação

| ID | Requisito | Origem | Prio | Dono |
|---|---|---|---|---|
| RP-01 | O senhorio vê só totais por quarto e alertas (DTOs separados, testados) | PDF §2.2 | P0 | P5 |
| RP-02 | Sem frames gravados, sem reconhecimento facial, segredos fora do Git e dos logs | PDF §10.5, CLAUDE.md | P0 (restrição) | todos |
| RP-03 | Acesso, exportação e contestação dos dados pelo próprio morador | PDF §10.4 | P1 | P5 |
| RD-01 | Simulador de leituras e replay de um mês simulado (`provenance=simulated`) | PDF §17 (`simulated_month.csv`), adaptado | P0 | P1 |
| RD-02 | Rótulo REAL/SIMULADO visível em toda a UI e nos recibos | CLAUDE.md (herdado) | P0 | P5 |
| RD-03 | Reset da demo em menos de 1 minuto | PDF §17, §21 | P0 | P5 |
| RD-04 | Plano B sem hardware: tudo funciona com FakeHome + leituras simuladas | DECISÃO | P0 | P1 + P5 |

## Não-requisitos (explícitos)

Reconhecimento facial; gravação de vídeo; venda de dados; senhorio a ver presença; canais de mensagens externos e bots (D-01 em [decisions.md](../decisions.md)); painéis fora da aplicação; contadores novos (o PDF «sem contadores novos» mantém-se na intenção, com a tomada do kit no MVP).
