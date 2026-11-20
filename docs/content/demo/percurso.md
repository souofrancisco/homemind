# Percurso da aplicação

Cerca de 5 minutos, com dados **SIMULADOS**.

## 1. Morador (`ana`)

1. **Hoje:** consumo por tomada com a origem visível (medido / estimado / simulado) e os pedidos pendentes.
2. **Notificações** (sino no topo): pedido «De quem é esta conta?» (custo estimado, «0 de 4 votos»).
3. **«É minha»:** a decisão é imediata; os outros moradores veem que a utilização não fica a seu cargo.
4. **Contas → Este mês:** definir o orçamento de 35 € por mês; o consumo assumido conta em «O teu quarto».

## 2. Senhorio (`senhorio`)

1. **Contas:** nova fatura de 120 € (01–18/11, parte fixa 15 €, 400 kWh).
2. **Pré-visualizar** (nada é gravado) → **registar** (rascunho) → **Finalizar e repartir**.
3. O **Hoje** do senhorio mostra só a casa e os atalhos para Contas e Casa: o senhorio não vê consumo detalhado, presença nem aparelhos.

## 3. Moradores (`ana`, `bruno`, `carla`, `diogo`)

**Contas → Recibos → «Porque pago isto?»**: os quatro valores somam exatamente 120,00 € e cada recibo explica a repartição entre quarto, zona comum e resíduo.

## Guião de 3 minutos (proposta)

| Tempo | O que acontece |
|---|---|
| 0:00 | O problema: «120 € ÷ 4 = 30 € para todos, mas o Bruno tem um aquecedor» |
| 0:25 | Casa de 4 moradores; aparelhos registados |
| 0:50 | Liga-se o aquecedor; «Provável: aquecedor do Bruno» (inferido, nunca «certo») |
| 1:15 | O Bruno responde «É minha» |
| 1:45 | O orçamento sobe; aviso de 80 % |
| 2:10 | Fecho do mês: recibos «medido / estimado / simulado» e botão de contestar |
| 2:35 | Painel do senhorio: só totais por quarto |

O guião de 3 minutos é uma **PROPOSTA**. Nada se diz como REAL sem validação nesse dia.

*Fontes canónicas: `docs/functional-flows.md`, `docs/development/mvp.md`, `app/frontend/src/app/routes.tsx`.*

!!! note "Navegação"
    Os passos seguem a navegação atual (Hoje, Contas, Casa). A validação no browser de 2026-11-18 foi feita com a navegação anterior; este percurso ainda não foi repetido no browser com a atual.
