---
title: Início
hide:
  - toc
  - navigation
---

<section class="hero" markdown>

<p class="hero__eyebrow">Aveiro Tech City Hackathon 2026 · Desafio 3, Altice Labs</p>

# Conta Certa

<p class="hero__lead">
<strong>Cada um paga o que usa. A casa trata do resto.</strong><br>
Serviço para casas partilhadas: lê o consumo elétrico por tomada, atribui cada consumo a um morador ou à conta comum (perguntando na aplicação quando há dúvida), divide a fatura de forma explicada e avisa antes de o orçamento de cada um chegar ao limite.
</p>

[Ver o produto](produto/index.md){ .md-button .md-button--primary }
[Percurso da demo](demo/percurso.md){ .md-button }
[Estado do projeto](progresso/index.md){ .md-button }

</section>

## O problema

Nas casas partilhadas a conta da luz divide-se por igual. Quem só carrega o portátil paga o aquecedor de 2 kW do colega, as discussões repetem-se todos os meses e quem tem menos dinheiro deixa de aquecer o quarto. Os dados existem nos contadores e sensores, mas não chegam às pessoas.

## Proposta de valor

<div class="grid cards" markdown>

- **Casa Justa**

    O teu quarto é teu; as zonas comuns são de todos. Cada recibo explica porque pagas o que pagas e distingue valores medidos, estimados e simulados.

- **Casa Atenta**

    O sistema avisa do que não bate certo: orçamento a 50/80/100 %, picos em zonas comuns, aparelho pessoal fora do quarto.

- **Casa Segura**

    Presença sem vigilância: o vídeo é só local, nada é gravado nem enviado, e o senhorio nunca vê presença, horários ou imagens.

</div>

## Estado atual

!!! warning "Tudo na demonstração é SIMULADO"
    O que funciona hoje foi validado no browser com dados **simulados** (FakeHome e dados de demonstração). Nada foi validado com hardware real ponta a ponta. A página [Funcionalidades verificadas](demo/verificado.md) separa o que foi visto no browser, o que só tem testes e o que nunca foi validado.

Distinguimos sempre três estados: <span class="estado estado--ok">IMPLEMENTADO</span> existe na `main`; <span class="estado estado--plan">PLANEADO</span> está decidido mas por construir; <span class="estado estado--prop">PROPOSTA</span> é uma ideia da equipa sem decisão.

## Por onde começar

| Quero… | Ir para |
|---|---|
| Perceber o produto | [Produto](produto/index.md) |
| Ver como está construído | [Arquitetura](arquitetura/index.md) |
| Correr o projeto | [Desenvolvimento](desenvolvimento/index.md) |
| Ver a demonstração | [Demonstração](demo/index.md) |
| Saber quem faz o quê | [Equipa](equipa/index.md) |
| Saber o que está feito e o que falta | [Progresso](progresso/index.md) |
