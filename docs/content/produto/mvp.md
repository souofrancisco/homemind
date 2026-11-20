# MVP

O MVP demonstra o problema principal, **dividir a conta com justiça e explicação**, com as limitações reais do kit: **uma única tomada com medição**.

## Âmbito

O MVP é a **Casa Justa + Casa Atenta**.

| Dentro do MVP | Fase 2 / fora |
|---|---|
| Casa com 4 moradores (seed) | Segurança com a casa vazia, aparelho esquecido |
| Registo de aparelhos pessoais e comuns | Cenários e regras por conversa |
| Leituras de consumo (tomada real ou simulador) | Total da casa em tempo real, HAN, MEO Energia |
| Degraus e identificação **provável** (com `confidence`) | Várias tomadas de quarto (só em produção) |
| Contagem na porta, Wi-Fi opt-in ou presença manual | Push, leitura de faturas por LLM |
| Notificação «De quem é esta conta?» na aplicação | Opção C da sala por presença |
| Orçamento 50/80/100 %, pico em zona comum, lâmpada RGB (se validada) | Previsão avançada e bi-horário |
| Assistente na aplicação, só com ferramentas de leitura | Ações propostas pela IA |
| Fatura, recibos e painel do senhorio; REAL / SIMULADO / ESTIMADO visível | |

O que já está implementado de cada linha está em [Funcionalidades](funcionalidades.md); esta página descreve o âmbito, não o estado.

## Limitações assumidas

Uma só tomada mede a extensão da bancada. A identificação por uma tomada é **probabilística** (cargas simultâneas e a sua localização não se inferem com certeza): cada resultado leva `confidence` e o resíduo divide-se por igual.

## Plano B

Toda a demonstração corre com `HOME_BACKEND=fake` e leituras simuladas, **sem rede, sem câmara, sem MCP**. A interface mostra SIMULADO em tudo e isto diz-se sempre em voz alta. Ver [Real, estimado e simulado](../demo/proveniencia.md).

*Fonte canónica: `docs/development/mvp.md`.*
