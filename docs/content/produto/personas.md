# Personas

Três papéis. As permissões aplicam-se **no servidor**, com DTOs de resposta distintos por papel; a aplicação cliente nunca é a barreira.

## Senhorio (`landlord`)

Gere casas, quartos, contratos e faturação, **com acesso limitado aos dados pessoais dos moradores**.

| Pode | Não pode (por desenho) |
|---|---|
| Criar casas e quartos; associar moradores e datas | Ver presença, entradas/saídas, horários ou curvas horárias |
| Definir tarifa, parte fixa e plafond por quarto | Ver imagens ou vídeo da câmara |
| Registar a fatura mensal | Ver os aparelhos individuais de cada morador |
| Ver **totais mensais por quarto** e alertas | Atribuir ou alterar consumos individuais |
| Fechar a fatura e publicar os recibos | Ver notificações pessoais ou contestar em nome do morador |

## Inquilino (`tenant`)

Acompanha o seu consumo, configura orçamentos, confirma utilizações e consulta recibos.

- Vê o seu consumo e os seus aparelhos; define o orçamento pessoal e os limiares de aviso.
- Responde a pedidos («É minha», «Escolher responsável(eis)», «Não sei»); a resposta fica registada com autor e hora e pode ser contestada.
- Pode optar por registar presença (opt-in) e retirá-la quando quiser; pode consultar e exportar os seus dados.

## Operador (`operator`)

Papel técnico: configura a integração com os dispositivos e gere a demonstração. Escritas físicas só com `ENABLE_PHYSICAL_WRITES=true` **e** autorização temporária.

## Matriz resumida

| Recurso | Senhorio | Inquilino | Operador |
|---|---|---|---|
| Totais por quarto (mensais) | ✔ | ✔ (da casa) | — |
| Consumo detalhado e aparelhos | ✘ | ✔ (o seu) | — |
| Presença / entradas e saídas | ✘ | ✔ (a sua, opt-in) | — |
| Imagens da câmara | ✘ | ✘ | só diagnóstico local, sem gravar |
| Fatura e recibos | ✔ (todos) | ✔ (o seu) | — |
| Pedidos de confirmação | ✘ | ✔ | — |
| Configuração MCP / dispositivos | ✘ | ✘ | ✔ |

A matriz é o desenho; a implementação foi verificada por amostra, não de forma exaustiva ([ver isolamento](../demo/verificado.md#isolamento-por-papel)).

*Fonte canónica: `docs/product/personas.md`.*
