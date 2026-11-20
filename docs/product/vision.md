# Visão do produto — Conta Certa

> **Cada um paga o que usa. A casa trata do resto.**

Fonte: [Documento completo](../references/Conta_Certa_Documento_Completo.pdf) e [Sumário executivo](../references/Sumario_Executivo_Conta_Certa.pdf), com a alteração de [decisions.md](../decisions.md) (D-01): **a aplicação substitui o Telegram**.

## O problema

Nas casas partilhadas a conta da luz divide-se por igual. Quem só carrega o portátil paga o aquecedor de 2 kW do colega, as discussões repetem-se todos os meses e quem tem menos dinheiro deixa de aquecer o quarto. Os dados existem nos contadores e sensores, mas não chegam às pessoas (PDF §1). Os números do PDF (447 680 estudantes, 14,5 % sem capacidade de aquecer a casa, 8 % de cobertura de residências) estão citados e referenciados nesse documento; **não os repetimos aqui como verificados por nós**.

## A solução

Um serviço que o **senhorio** instala e que usa o kit Connected Home da Altice (tomadas com medição, lâmpada, sensores, câmara) através do MCP para:

1. medir o consumo e reconhecer aparelhos pela assinatura elétrica;
2. atribuir cada consumo a um morador ou à conta comum, perguntando na aplicação quando há dúvida;
3. dividir a fatura de forma justa e explicada;
4. avisar antes de a conta chegar ao limite de cada um;
5. saber quando a casa fica vazia, sem reconhecer ninguém (fase 2: casa vazia/AWAY está fora do MVP).

A interface principal é a **aplicação da Conta Certa** (React, Mantine, Capacitor), para moradores e senhorios. O assistente de IA vive dentro da aplicação.

## Os três pilares

| Pilar | Promessa | Funcionalidades (ver [requirements.md](requirements.md)) |
|---|---|---|
| **Casa Justa** | Cada um paga o que consumiu | Medição, assinaturas de aparelhos, atribuição a quartos e moradores, divisão da fatura, recibos explicáveis, contestação |
| **Casa Atenta** | A casa avisa antes de a conta doer | Orçamentos, previsões, anomalias, picos em zonas comuns, aparelhos esquecidos, recomendações |
| **Casa Segura** | Sabe quando a casa está vazia, sem olhar para ninguém | Presença (contagem na porta, estados da casa), entradas e saídas, alertas, automações autorizadas |

A frase que resume a divisão justa (PDF §6.10): *o teu quarto é teu; as zonas comuns são de todos; o sistema avisa do que não bate certo.*

## Princípios de desenho

Herdados do PDF §2.2, mantidos:

- **Quarto = pessoa.** Medir o quarto é medir a pessoa, sem seguir ninguém pela casa. A ligação pessoa–quarto vem do contrato de arrendamento.
- **A câmara não sabe quem és.** Só conta entradas e saídas na porta; nunca grava nem identifica caras.
- **O senhorio vê faturas, não pessoas.** Totais por quarto e alertas; nunca presença, horários ou imagens.
- **Justiça com rede de segurança.** Plafond solidário para o aquecimento básico.
- **O pior caso é o de hoje.** O que o sistema não consegue atribuir divide-se por igual.
- **Não depende da honestidade.** O que vale dinheiro mede-se de forma passiva; as fontes verificam-se entre si.

Acrescentados por esta reorganização:

- **A aplicação é o canal único.** Toda a interação (perguntas, alertas, confirmações, assistente) acontece na aplicação. Não há bot nem grupo de mensagens externo.
- **Proveniência sempre visível.** Cada número distingue `measured`, `estimated`, `inferred` e `simulated` ([data-model.md](../architecture/data-model.md)). Nunca se apresenta simulação como real.
- **Honestidade sobre os limites.** Com uma única tomada de medição não prometemos identificação perfeita de aparelhos ([development/mvp.md](../development/mvp.md)).

## O que a Conta Certa não é

- Não é vigilância: nada de reconhecimento facial, gravação, imagens ao senhorio, venda de dados (PDF §10.5).
- Não vende eletricidade: o senhorio só reparte o custo real da fatura (PDF §10.3; validação jurídica por fazer).
- Não é um contador certificado: os valores são medições do kit ou estimativas, e cada recibo diz qual é qual.
- Não é (ainda) um sistema de segurança: o armar de alarmes e os cenários do Connected Home estão **fora do âmbito atual** do MCP do projeto (ver [integrations/altice-mcp.md](../integrations/altice-mcp.md)).

## Duas camadas de adoção (v5.1 §11.2)

| Nível | Equipamento | Entrega |
|---|---|---|
| 1 · Base | Tomada, lâmpada e sensores por quarto | Aquecedores medidos, três regras, orçamento e avisos |
| 2 · Presença | + câmara na porta + telemóveis registados | Conta da sala por presença, estado da casa (fase 2: aparelhos esquecidos, AWAY) |

O v5.1 retirou o módulo HAN e o contador geral em tempo real do desenho-base (D-16). O MVP da hackathon corresponde a uma versão reduzida do nível 1: **uma só tomada com medição** faz de medidor da bancada ([development/mvp.md](../development/mvp.md)).

## Para a Altice

Junta a fibra MEO, a MEO Energia e a plataforma Connected Home num serviço recorrente por quarto, com equipamento que fica na casa quando os inquilinos mudam (PDF §15.4). Preços, receitas e payback do PDF são **hipóteses a validar**, não resultados nossos.
