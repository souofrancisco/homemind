# Personas e limites de acesso

Três personas (PDF §2, §11, §24). Os papéis concretos são do tipo `Membership.role` ([data-model.md](../architecture/data-model.md)). **PROPOSTA** onde o PDF não é explícito.

## Senhorio (`landlord`)

Gere casas, quartos, contratos e faturação, **com acesso limitado aos dados pessoais dos moradores**.

| Pode | Não pode (nunca, por desenho) |
|---|---|
| Criar casas e quartos; associar moradores (do contrato) e datas | Ver presença, entradas/saídas, horários ou curvas horárias de consumo |
| Definir tarifa, parte fixa, plafond solidário e plafond por quarto | Ver imagens ou vídeo da câmara |
| Registar a fatura mensal (ou carregá-la, quando existir leitura automática) | Ver os aparelhos individuais de cada morador (**PROPOSTA**: só totais) |
| Ver **totais mensais por quarto** e alertas (consumo acima do plafond, segurança) | Atribuir ou alterar consumos individuais |
| Fechar a fatura e publicar os recibos | Ver notificações pessoais dos moradores |
| Receber alertas de segurança só quando a casa está vazia (PDF §8) | Contestar em nome do morador |

Percurso: *convida moradores → configura quartos e plafond → regista a fatura do mês → revê os totais por quarto → fecha a fatura → os moradores recebem os recibos.*

## Inquilino (`tenant`)

Acompanha o seu consumo, configura orçamentos, confirma utilizações e consulta recibos.

| Pode | Limites |
|---|---|
| Ver o seu consumo, os seus aparelhos e a conta da sala | Só vê o seu detalhe; dos outros vê totais da casa e dos quartos (**PROPOSTA**, a decidir: [decisions.md](../decisions.md) P-04) |
| Registar aparelhos pessoais e partilhados | Não altera regras da casa sozinho (votação/acordo: **PROPOSTA**) |
| Definir o orçamento pessoal e os limiares de aviso (50/80/100 %) | |
| Responder a pedidos: **É minha / Escolher responsável(eis) / Não sei** (D-38) | A resposta fica registada com autor e hora; pode ser contestada |
| Contestar consumos e recibos | |
| Consultar histórico de notificações e definir preferências (silêncio noturno, limiares) | |
| Falar com o assistente de IA sobre o seu consumo e recibos | O assistente só acede aos dados que o próprio utilizador pode ver |
| Optar por registar presença (opt-in) e retirá-la quando quiser | |
| Consultar, exportar e contestar os seus dados (PDF §10.4) | |

Percurso: *recebe convite → entra na casa → regista aparelhos e (opcional) presença → define orçamento → recebe avisos → confirma utilizações → consulta o recibo e, se discordar, contesta.*

## Administrador / operador (`operator`)

Configura a integração com os dispositivos e gere a demonstração. É um papel **técnico** (na hackathon, a equipa).

| Pode | Limites |
|---|---|
| Configurar o MCP (login OAuth no host), escolher a lâmpada e a tomada, definir a unidade de `instantPower` | Escritas físicas só com `ENABLE_PHYSICAL_WRITES=true` **e** grant temporário (ver [integrations/mcp-demo.md](../integrations/mcp-demo.md)) |
| Ver diagnóstico: estado do MCP, câmara, último contacto dos dispositivos | Não vê dados pessoais de consumo por defeito (**PROPOSTA**) |
| Correr o simulador de leituras e o reset da demo (dados `simulated`, sempre marcados) | Nunca se apresenta simulação como real |
| Gerir casas de demonstração | |

## Matriz resumida (planeada)

| Recurso | Senhorio | Inquilino | Operador |
|---|---|---|---|
| Totais por quarto (mensais) | ✔ | ✔ (da casa) | — |
| Consumo detalhado e aparelhos | ✘ | ✔ (o seu) | — |
| Presença / entradas e saídas | ✘ | ✔ (a sua, opt-in) | — |
| Imagens da câmara | ✘ | ✘ | só diagnóstico local, sem gravar |
| Fatura e recibos | ✔ (todos) | ✔ (o seu) | — |
| Pedidos de confirmação | ✘ | ✔ | — |
| Configuração MCP / dispositivos | ✘ | ✘ | ✔ |
| Assistente de IA | ✘ (**PROPOSTA**) | ✔ | — |

**Aplicação no código:** as permissões aplicam-se no servidor, com DTOs de resposta distintos por papel (o senhorio nunca recebe campos de presença ou aparelhos). Teste obrigatório em [development/testing.md](../development/testing.md). A aplicação cliente nunca é a barreira.
