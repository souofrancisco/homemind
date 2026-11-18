# Contador geral (HAN / E-REDES) e MEO Energia — inventário e plano B (PILOT-02)

> **Estado: PROPOSTA / estudo de secretária (PILOT-02 #126, F3, P2).** Nada deste documento está implementado nem foi ensaiado em hardware. **Não bloqueia o MVP**: a decisão D-16 mantém-se (sem HAN nem contador geral como dependência; v5.1 §26.11). Pesquisa feita a **2026-11-18**; as fontes estão no fim.

## Conclusão

1. **A porta HAN existe e é pedida por quem tem contador inteligente em baixa tensão normal**, mas exige hardware próprio (módulo Modbus em RJ12), pedido à E-REDES e agendamento. Não está provado quanto custa nem que dados expõe em detalhe (a página oficial não o diz).
2. **O Smart Metering Plus** (acesso virtual à porta HAN por API) é, segundo a E-REDES, **um serviço em desenvolvimento, em piloto**. Não há documentação pública de endpoints, autenticação nem inscrição, e não se sabe se o piloto ainda corre.
3. **MEO Energia:** não foi encontrada **nenhuma API pública** de faturas, tarifas ou consumos. Só canais para o cliente (área MyMEO, app, leituras, email). Falta de documentação pública **não prova** que não exista acesso interno: é uma pergunta para a Altice.
4. **Plano B (já é o MVP):** tomadas por quarto + fatura mensal inserida à mão. O total do mês fecha a repartição e não precisa de tempo real (v5.1, linha «Total do mês»; D-16).

## Etiquetas de evidência

- **COMPROVADO** — lido numa página ou PDF oficial da E-REDES (consultado a 2026-11-18).
- **INDICADO** — aparece em fonte secundária (imprensa, comparadores, fóruns); **não** é facto nosso.
- **NÃO COMPROVADO** — não se encontrou; **não** assumir.

## Inventário de interfaces

| Interface | O que dá | Acesso e requisitos | Evidência |
|---|---|---|---|
| **Porta de comunicação série (HAN)** do contador inteligente (EMI) | «Conhecer o consumo de energia em tempo real». Campos, formato e frequência **não** descritos na página | Instalação em baixa tensão normal com contador inteligente. Pedido no portal **Contador Digital** e agendamento com a E-REDES. O módulo é **da exclusiva responsabilidade do cliente** | COMPROVADO (página da E-REDES) |
| **Módulo HAN: requisitos técnicos** (versão 3, 2020/12) | Protocolo **Modbus**; interface **RJ12 macho**; máx. **70 mA a 5 V**; máx. **1 pedido por segundo**; marcação CE | Dois tipos: (a) alimentado pela interface HAN, **sem pré-aprovação** (o requisitante responde por danos); (b) alimentado/acoplado à rede BT sob a tampa de terminais, **com aprovação prévia** (gerida pela E-REDES, executada pela EDP Labelec), isolamento classe II, < 30×80×20 mm. Ligação ao contador por **chicote fornecido pela E-REDES** | COMPROVADO (PDF dos requisitos) |
| Partilha da interface HAN com a comunicação remota da E-REDES | Em contadores com a interface RS485/HAN partilhada, o acesso do módulo pode **ser interrompido momentaneamente** durante a comunicação remota ou manutenção | — | COMPROVADO (mesmo PDF) |
| **Smart Metering Plus** (piloto) | Acesso «quase em tempo real» virtualizando a porta HAN. API padronizada com dados em bruto. No piloto, só um subconjunto: potência instantânea importada e exportada, totalizadores de energia, potência máxima, tensão instantânea. Atualização «normalmente inferior a 10 s», **não garantida** | Participantes do piloto, sem custos adicionais **no piloto**. Também no Contador Digital e na app E-REDES | COMPROVADO (página Smart Meters) |
| Dados em intervalos de 15 min no Balcão Digital / app E-REDES | Diagrama de carga (blocos de 15 min) | Do próprio cliente | INDICADO (comparadores, fóruns; a ERSE refere recolha diária com detalhe de 15 min) |
| **MEO Energia** — área MyMEO / app | Faturas (as últimas 12, segundo fontes secundárias); envio de leituras | Conta de cliente MEO Energia | INDICADO |
| MEO Energia — email diário | Perfil horário de consumo e estimativa de preço do dia seguinte (imprensa) | Cliente aderente | INDICADO (não é API) |
| **API pública da MEO Energia** (faturas, tarifas, consumo) | — | — | **NÃO COMPROVADO** (nada encontrado) |

## Lacunas (não assumir)

- **HAN:** campos expostos, frequência real e formato; **preço do pedido**. A página oficial não indica valor e remete para as tarifas da ERSE; os «~14 € + IVA» que aparecem em fóruns são **INDICADOS**, de utilizadores, e não foram verificados.
- **Quem pode pedir** num imóvel arrendado: a página fala em «a sua instalação». Não diz se o pedido tem de ser do **titular do contrato** (senhorio ou inquilino). **Pergunta aberta.**
- **Smart Metering Plus:** estado atual do piloto (a página não tem datas), critérios e inscrição, endpoints, autenticação, limites de pedidos, preço depois do piloto.
- **Consentimento a terceiros** (comercializadores, agregadores): a página lida do Smart Metering Plus não descreve o processo. Resultados de pesquisa referem consentimento no Balcão Digital; **não confirmado**.
- **MEO Energia:** existência de API ou exportação para parceiros. Só a Altice/MEO Energia o pode dizer.
- **Hardware:** preço e disponibilidade de um módulo HAN compatível. **Não pesquisado.**

## Custos de implantação (o que se sabe)

| Item | Estado |
|---|---|
| Pedido de acesso à porta HAN | **Valor não comprovado** (ver lacunas) |
| Módulo HAN (hardware) | **Não pesquisado**; responsabilidade do cliente |
| Instalação | Agendada com a E-REDES; quem instala e em que condições **não está na página** |
| Smart Metering Plus | Sem custo **no piloto**; depois **desconhecido** |
| Integração MEO Energia | **Desconhecido** |

## Plano B (IMPLEMENTADO no MVP)

Tomada por quarto com medição, mais a fatura mensal inserida à mão; o senhorio só reparte o custo real da fatura (D-16; o enunciado do #126 fixa «MVP mantém entrada manual e uma tomada»; ver também [mvp.md](../development/mvp.md)). Sem contador geral, o «resíduo» da casa fecha-se pelo total da fatura, não por leitura em tempo real. Se o acesso à E-REDES ou à MEO Energia não existir, **nada muda no produto**.

## Se a equipa quiser avançar (PROPOSTA, depois do MVP)

1. Perguntar à **E-REDES** (apoio ao cliente / Contador Digital): quem pode pedir a porta HAN num arrendamento, preço, dados e frequência expostos, e estado/inscrição do Smart Metering Plus.
2. Perguntar à **Altice/MEO Energia** (mentores): há API ou exportação de faturas e tarifas? Ver [mentor-questions.md](mentor-questions.md), perguntas 11 e 12.
3. Só com respostas **escritas** e acesso confirmado abrir tarefas técnicas (contrato de leitura, conector, testes com fixtures). Nenhuma foi aberta.

Preferência provisória: se o acesso ao contador vier a interessar, o caminho com menos atrito para um senhorio é **Smart Metering Plus** (sem módulo físico), quando deixar de ser piloto, e não o módulo HAN próprio.

## Fontes (consultadas a 2026-11-18)

- E-REDES — acesso à porta de comunicação série: <https://www.e-redes.pt/en/energy-transition/networks-of-the-future/serial-communication-port-access>
- E-REDES — requisitos dos módulos HAN (versão 3, 2020/12): <https://www.e-redes.pt/sites/eredes/files/2021-04/Requisitos%20dos%20m%C3%B3dulos%20HAN.pdf>
- E-REDES — Smart Meters / Smart Metering Plus: <https://www.e-redes.pt/en/energy-transition/smart-meters>
- ERSE — redes inteligentes (dados a 15 min; só resumo de pesquisa, página não lida na íntegra): <https://www.erse.pt/atividade/regulamentos-eletricidade/redes-inteligentes/>
- Fontes secundárias **INDICADAS** (comparadores e imprensa, não oficiais): comparamais.pt (faturas MEO Energia), Executive Digest (serviço informativo da MEO Energia).
