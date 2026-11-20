# Visão e objetivos

> **Cada um paga o que usa. A casa trata do resto.**

## O problema

Nas casas partilhadas a conta da luz divide-se por igual. Quem só carrega o portátil paga o aquecedor de 2 kW do colega, as discussões repetem-se todos os meses e quem tem menos dinheiro deixa de aquecer o quarto.

Os números de contexto (estudantes sem capacidade de aquecer a casa, cobertura de residências) vêm do documento de proposta da equipa e **não são resultados nossos verificados**.

## A solução

Um serviço que o **senhorio** instala e que:

1. mede o consumo e reconhece aparelhos pela assinatura elétrica;
2. atribui cada consumo a um morador ou à conta comum, perguntando na aplicação quando há dúvida;
3. divide a fatura de forma justa e explicada;
4. avisa antes de a conta chegar ao limite de cada um;
5. sabe quando a casa fica vazia, sem reconhecer ninguém (deteção «provavelmente vazia» só em testes; modo AWAY <span class="estado estado--plan">PLANEADO</span>, fase 2).

A interface é a **aplicação da Conta Certa** (React, Mantine), para moradores e senhorios. A aplicação é o canal único: não há bot nem grupo de mensagens externo.

## Os três pilares

| Pilar | Promessa | Funcionalidades |
|---|---|---|
| **Casa Justa** | Cada um paga o que consumiu | Medição, assinaturas de aparelhos, atribuição a quartos e moradores, divisão da fatura, recibos explicáveis, contestação |
| **Casa Atenta** | A casa avisa antes de a conta doer | Orçamentos, previsões, anomalias, picos em zonas comuns, recomendações |
| **Casa Segura** | Sabe quando a casa está vazia, sem olhar para ninguém | Contagem na porta, estados da casa, alertas, automações autorizadas |

## As três regras da divisão

1. **O teu quarto é teu.** O que passa pela tomada do quarto é do morador.
2. **As zonas comuns são de todos.** Por igual, ou com a pergunta «de quem é esta conta?».
3. **O sistema avisa do que não bate certo.** Orçamento a 50/80/100 %, picos em zonas comuns, aparelho pessoal fora do quarto.

## Princípios de desenho

- **Quarto = pessoa.** Medir o quarto é medir a pessoa, sem seguir ninguém pela casa. A ligação pessoa–quarto vem do contrato de arrendamento.
- **A câmara não sabe quem és.** Só conta entradas e saídas na porta; nunca grava nem identifica caras.
- **O senhorio vê faturas, não pessoas.** Totais por quarto e alertas; nunca presença, horários ou imagens.
- **Justiça com rede de segurança.** Plafond solidário opcional para o aquecimento básico.
- **O pior caso é o de hoje.** O que o sistema não consegue atribuir divide-se por igual.
- **Proveniência sempre visível.** Cada número distingue `measured`, `estimated`, `inferred` e `simulated`. Nunca se apresenta simulação como real.

## Duas camadas de adoção

| Nível | Equipamento | Entrega |
|---|---|---|
| 1 · Base | Tomada, lâmpada e sensores por quarto | Aquecedores medidos, três regras, orçamento e avisos |
| 2 · Presença | + câmara na porta + telemóveis registados | Conta da sala por presença, estado da casa |

O MVP da hackathon corresponde a uma versão reduzida do nível 1: **uma só tomada com medição** faz de medidor da bancada.

!!! note "Hipóteses comerciais"
    Preços, receitas e payback do documento de proposta são **hipóteses a validar**, não resultados.

*Fonte canónica: `docs/product/vision.md` no repositório.*
