# Conta Certa

**Desafio 3 · Altice Labs Connected Home · Aveiro Tech City Hackathon 2026**

*A casa partilhada onde cada um paga o que usa — adotada pelo senhorio, com IA, visão por computador e o kit Connected Home.*

> “Cada um paga o que usa. A casa trata do resto.”

| Justa | Atenta | Segura *(fase 2)* | Inteligente |
|---|---|---|---|
| Consumo por quarto e por pessoa; a fatura dividida pelo que cada um usou. | Orçamento mensal e picos nas zonas comuns: avisa antes de a conta doer. | Sabe quando a casa fica vazia — sem reconhecer ninguém — e arma a segurança sozinha. | Um agente de IA no grupo da casa (os 4 moradores + o bot) que age através do MCP. |

Documento final de estudo e apresentação · **Versão 5.1** · 17 de novembro de 2026
Parte A — A ideia · Parte B — Plano de desenvolvimento · Parte C — Preparar a apresentação

---

## Resumo executivo

Em Portugal, milhares de estudantes vivem em quartos arrendados onde a luz é dividida em partes iguais, o aquecimento gera conflitos e ninguém sabe ao certo quem gastou o quê.

| 8% | 14,5% | 447 680 | 99% |
|---|---|---|---|
| taxa de cobertura de residências universitárias — a maioria dos estudantes depende de quartos privados | da população não conseguia aquecer a casa em 2024 — 4.º pior valor da UE (média 9,2%) | estudantes no ensino superior em 2025/2026 (DGES) | das casas têm contador inteligente — mas o dado chega à casa, não à pessoa |

Conta Certa é um serviço que o senhorio instala nas suas casas. Quem arrenda um quarto sabe desde o anúncio que a luz é dividida pelo consumo de cada quarto. Dentro da casa, um agente de Inteligência Artificial vive no grupo de mensagens (os 4 moradores + o bot), lê os dispositivos através do MCP Connected Home e age sobre eles. Faz três coisas:

| O quê | O que faz | Dispositivos e IA |
|---|---|---|
| **Justa** | Três regras: o teu quarto é teu, as zonas comuns são de todos, o sistema avisa. Reconhece aparelhos pela assinatura em qualquer tomada, sabe quem está em casa sem olhar para ninguém e avisa antes do limite mensal. | Tomada, câmara na porta, Wi-Fi · assinaturas, presença, alertas |
| **Atenta** | Orçamento pessoal com avisos aos 50/80/100% e picos nas zonas comuns. | Tomada, Wi-Fi, lâmpada · previsão, anomalias |
| **Segura** *(fase 2)* | Sabe quando a casa fica vazia e arma a segurança; alerta para entradas com a casa vazia; avisa de aparelhos esquecidos. | Câmara na porta, contacto · presença |

**Três decisões que tornam o projeto adotável e defensável:**

1. **Quem adota é o senhorio** — o inquilino escolhe a casa já a saber as regras; ninguém pode vetar depois.
2. **A câmara nunca grava nem reconhece caras.** Fica na porta e só conta entradas e saídas; quem é vem do telemóvel registado (opt-in).
3. **Não depende da honestidade de ninguém.** O que vale dinheiro mede-se sem cooperação e os sensores verificam-se uns aos outros.

> **O momento WOW:** o “João” chega a casa (a câmara conta uma entrada, o telemóvel dele liga-se ao Wi-Fi) e liga na sala o aquecedor do Bruno. A IA reconhece o aparelho pela assinatura, percebe que não está no quarto do Bruno e pergunta no grupo “de quem é esta conta?” — o João carrega em “é minha”. Minutos depois recebe: “já gastaste 80% do teu orçamento”.

**Para a Altice:** junta a fibra MEO, a MEO Energia e a plataforma Connected Home num serviço recorrente vendido a senhorios e residências, com equipamento que fica na casa quando os inquilinos mudam.

---

## Índice

**Parte A — A ideia**

1. O problema real
2. A solução e o modelo do senhorio
3. Enquadramento na casa inteligente e onde entra a IA
4. O que cada dispositivo faz
5. A câmara: na porta de entrada
6. Casa justa: as regras e os motores
7. O modelo de divisão justa
8. À prova de batota
9. Os modelos de IA
10. Privacidade e enquadramento legal
11. Facilidade de adoção
12. A experiência: conversas com a casa
13. Use cases fora da caixa
14. Impacto no mundo real
15. Viabilidade e sustentabilidade

**Parte B — Plano de desenvolvimento**

16. Arquitetura do MVP
17. Repositório, módulos e contrato de eventos
18. Montagem da bancada de demo
19. Plano de 2 dias por pessoa
20. Hora zero: verificações e planos B
21. Testes e ensaio
22. Guião da demo de 3 minutos

**Parte C — Preparar a apresentação**

23. Perguntas difíceis do júri
24. Riscos e mitigação
25. Autoavaliação pelos critérios
26. Pontos a repensar antes do pitch

—. Fontes

> **Como usar este documento.** Para estudar a ideia: o resumo e as secções 1 a 6. Para apresentar aos colegas: secções 2, 4, 5, 6 e 22. Para desenvolver: Parte B inteira, começando pela secção 20 (hora zero). Para o pitch: secções 22, 23, 25 e 26.

---

# PARTE A — A IDEIA

## 1 O problema real

### 1.1 Casas partilhadas: contas injustas e conflitos

No ano letivo 2025/2026 havia 447 680 estudantes no ensino superior (DGES) e a taxa de cobertura de residências universitárias ronda os 8%. A maioria dos estudantes deslocados vive em quartos arrendados — em Lisboa um quarto já ronda os 500 € por mês. Nestas casas acumulam-se quatro problemas:

| Problema | O que acontece | Quem sofre |
|---|---|---|
| **Contas injustas** | A luz divide-se por igual. Um aquecedor de 2 kW ligado 6 h por noite gasta ~360 kWh/mês — mais do que todo o resto de um quarto normal. Quem gasta pouco paga por quem gasta muito; ninguém tem razão para poupar. | Inquilinos, ambiente |
| **Risco nas “despesas incluídas”** | O senhorio absorve abusos e responde subindo o preço para todos; gerir conflitos entre inquilinos exige tempo e mediação. | Senhorios e inquilinos |
| **Frio** | 14,5% da população não conseguia aquecer a casa em 2024 (4.º pior valor da UE). Numa divisão por consumo mal desenhada, o colega com menos dinheiro deixa de aquecer o quarto. | Inquilinos vulneráveis |
| **Esquecimentos** | Aquecedores ligados com a casa vazia, aparelhos esquecidos — e ninguém sabe que a casa ficou vazia. | Todos |

### 1.2 Os dados existem, mas não chegam às pessoas

A E-REDES instalou 6,6 milhões de contadores inteligentes e ~99% das instalações domésticas já os têm. Medem a casa inteira, mas não dizem quem consumiu. A camada que falta é a inteligência que junta os dados e age — é essa camada que a Conta Certa constrói.

### 1.3 Validação do problema (fazer antes do pitch)

**Inquérito rápido (meta: 30+ respostas)**

1. Vives numa casa partilhada? Com quantas pessoas?
2. Como dividem a luz? (igual / incluída na renda / por quarto / outro)
3. Já houve discussões por causa da luz ou do aquecimento?
4. Já evitaste ligar o aquecimento para não pagar mais?
5. Já saíste de casa com um aquecedor ligado?
6. Aceitarias um sensor na porta que só conta entradas e saídas, sem gravar nem identificar ninguém?
7. Escolherias um quarto com “despesas por consumo”?

**Três conversas com senhorios**

- Quanto absorvem por mês com despesas incluídas no inverno?
- Quanto tempo gastam a mediar conflitos sobre as contas?
- Pagariam uma subscrição por quarto? Quanto?

**Resultados (preencher)**

| Indicador | Resultado |
|---|---|
| Já discutiram por causa da luz | [__%] |
| Já evitaram aquecer para poupar | [__%] |
| Já deixaram aparelhos ligados ao sair | [__%] |
| Aceitam sensor ótico sem gravação | [__%] |

---

## 2 A solução e o modelo do senhorio

O senhorio instala a Conta Certa. Quem arrenda já sabe as regras. Dentro da casa, um agente de IA ligado ao MCP Connected Home torna a casa justa, atenta e segura.

### 2.1 Do anúncio à fatura

| # | Momento | O que acontece |
|---|---|---|
| 1 | Senhorio contrata | Adere ao serviço MEO; o kit é instalado (equipamento em comodato, incluído na mensalidade). |
| 2 | Anúncio do quarto | “Despesas por consumo · plafond solidário de [X] kWh incluído · orçamento e avisos no telemóvel”. |
| 3 | Contrato | Cláusula clara sobre a divisão por consumo e sobre a câmara, que não grava nem identifica pessoas (secção 10). |
| 4 | Entrada na casa | O inquilino lê um QR na porta e entra no grupo da casa (os 4 moradores + o bot); o agente apresenta-se e explica as regras. |
| 5 | Dia a dia | Cor da lâmpada, avisos de orçamento e de picos, regras votadas, previsão da fatura. |
| 6 | Fim do mês | Recibo individual explicado. O senhorio vê totais por quarto e alertas — nunca quem está em casa. |

### 2.2 Princípios de desenho

| | |
|---|---|
| **Quarto = pessoa** — Medir o quarto é medir a pessoa, sem seguir ninguém pela casa. | **A câmara não sabe quem és** — Na porta, só conta entradas e saídas. Nunca grava, nunca identifica caras. |
| **O senhorio vê faturas, não pessoas** — Totais mensais por quarto e alertas; nunca presença, horários ou imagens. | **Não depende da honestidade** — Medição passiva e sensores que se verificam entre si. |
| **Justiça com rede de segurança** — Plafond solidário: o aquecimento básico é pago em comum. | **O pior caso é o de hoje** — O que o sistema não consegue atribuir divide-se por igual, como já se faz. |

---

## 3 Enquadramento na casa inteligente e onde entra a IA

Uma casa inteligente percebe, decide e age. A Conta Certa faz as três coisas, com IA onde ela acrescenta valor e o MCP Connected Home como a ponte entre o agente e os dispositivos.

### 3.1 Pilares da casa inteligente

| Pilar | O que a Conta Certa faz | Dispositivos · ferramentas MCP |
|---|---|---|
| **Energia** | Consumo por quarto e por aparelho, atribuição a pessoas, horas de vazio, corte de desperdício. | Tomada, lâmpada · `GET_DEVICE_DETAILS`, `UPDATE_DEVICE_CAPABILITIES` |
| **Segurança** *(fase 2)* | AWAY automático pela câmara da porta e pelo Wi-Fi; alerta para entradas com a casa vazia. | Câmara, contacto · `GET/PATCH_HOME_SECURITY_*` |
| **Conforto** | Plafond solidário: o aquecimento básico é pago em comum; aviso privado a quem está várias noites abaixo de 18 °C. | Sensor de clima, tomada |
| **Automação** | Regras em português, votadas pela casa e transformadas em cenários. | `POST_NEW_SCENARIO`, `PATCH_SCENARIO_ACTIVATION` |
| **Interação** | Agente no grupo da casa e feedback pela cor da luz — sem app nova. | Lâmpada RGB · agente LLM |

### 3.2 Onde entra a IA

| Camada | O que faz | Onde |
|---|---|---|
| **Perceber** | Visão por computador: entradas e saídas na porta, sobre a stream RTSP; presença pelo Wi-Fi. | Câmara (no edge) |
| **Interpretar** | Reconhecer aparelhos pela assinatura (machine learning); localizar (quarto ou zona comum), fundir pistas de presença, prever a fatura e o orçamento e detetar anomalias (estatística e regras). | Tomada, sensores, API do tempo |
| **Decidir e agir** | Agente LLM que usa as ferramentas MCP: cortar a tomada, mudar a lâmpada, criar cenários, consultar a segurança. | MCP Connected Home |
| **Conversar** | Alertas, perguntas, explicações e regras em linguagem natural. | Grupo de Telegram: os 4 moradores + o bot |
| **Aprender** | Aprende com as respostas da casa (“foste tu?”, “isto é o secador do Bruno”). | Agente + base de dados |

> **Porque é que encaixa no Desafio 3.** Usa os sete dispositivos do kit, cada um com uma função real; põe a câmara no centro da presença — a peça que liga a conta da sala, os avisos e a segurança; usa o MCP como foi pensado — um agente que lê e age, incluindo cenários e segurança; e resolve problemas reais e documentados, com um caminho comercial claro para a Altice.

---

## 4 O que cada dispositivo faz

| Dispositivo | Papel no projeto | Exemplo |
|---|---|---|
| **Câmara MEARI Mini 12S** | Na porta de entrada: conta entradas e saídas (sem identidade) a partir da stream RTSP → motor de presença; mais tarde, casa vazia e segurança. | “1 entrada às 18:02” + telemóvel do João no Wi-Fi → João em casa |
| **Tomada (mede W)** | Em produção: uma por quarto, no aquecedor. No MVP: à entrada da extensão, como medidor do total da demo. Corta por regra. | Mede os 1050 W do aquecedor da Ana; desliga-o quando a janela abre |
| **Sensor de clima** | Confirma em que quarto está o aquecimento; alimenta o plafond solidário (quarto abaixo de 18 °C). | “O teu quarto esteve abaixo de 16 °C em 4 noites” |
| **Sensor de contacto** | Janela do quarto (aberta + aquecedor = corte) ou porta de entrada (confirma saídas). | Janela aberta 5 min → aquecedor desligado |
| **Lâmpada RGB** | Feedback sem app: verde/âmbar/vermelho face ao orçamento; pisca quando uma regra atua. Consumo estimado (9 W × tempo × brilho). | Âmbar aos 80% do orçamento |
| **Detetor de fumo** | Mantém a sua função de segurança do kit; o alarme é partilhado no grupo (e, na fase 2, com o senhorio se a casa estiver vazia). | “Alarme de fumo em casa” |
| **Gateway 4G** | Liga todos os dispositivos; os avisos continuam a funcionar se a fibra falhar. | — |

> **Kit de produção.** Por quarto: tomada com medição + lâmpada RGB + sensor de clima + sensor de contacto (janela). Por casa: gateway + detetor de fumo + câmara na porta de entrada.

---

## 5 A câmara: na porta de entrada

A câmara fica virada para a porta de entrada, pelo lado de dentro. A sua função principal é saber quando alguém entra ou sai — o dado que liga todos os motores da casa. Analisa a imagem no próprio local, só envia eventos, nunca grava e nunca reconhece caras.

> *“A câmara não sabe quem és. Só sabe que alguém entrou.”*

### 5.1 O que faz

| Função | Como funciona | O que sai da câmara |
|---|---|---|
| **Entradas e saídas** | Deteção de pessoas + uma linha virtual na soleira da porta: conta quem a atravessa e em que sentido | “1 pessoa entrou às 18:02”, “1 pessoa saiu às 17:45” |
| **Quem é? (sem caras)** | A entrada é cruzada com o motor de presença: no mesmo minuto, o telemóvel do João ligou-se ao Wi-Fi | “Entrada às 18:02 → João (97%)” — a identidade vem do telemóvel, não da imagem |
| **Visitas** | Mais entradas do que telemóveis registados → há visitas em casa | “2 pessoas em casa sem telemóvel registado” (só número, sem imagem) |
| **Casa vazia** *(fase 2)* | Entradas e saídas equilibradas + nenhum telemóvel no Wi-Fi → casa vazia | Modo AWAY automático; verificação de aparelhos esquecidos |
| **Segurança** *(fase 2)* | Em AWAY, qualquer entrada sem telemóvel registado → alerta confirmado por deteção de pessoa | “Entrada com a casa vazia às 03:12” |

### 5.2 Porque é que a câmara é central

- É a dobradiça dos motores: a presença decide a conta da sala (opção “por quem estava em casa”) e a deteção de batota (“entrou alguém e um aparelho ligou, mas nenhum telemóvel está em casa”). Na fase 2, decide também os avisos de aparelhos esquecidos e o modo AWAY.
- Corrige as falhas do Wi-Fi: um telemóvel com dados móveis ou a dormir “desaparece” da rede; a câmara confirma se alguém saiu mesmo pela porta.
- Dá números que nenhum outro sensor dá: quantas pessoas entraram, incluindo visitas.

### 5.3 Garantias de privacidade

| Garantia | Como é cumprida |
|---|---|
| **Só vê a soleira da porta** | Tudo o que não é a zona da porta é tapado a preto antes de qualquer análise. |
| **Sem reconhecimento facial** | O modelo só deteta a classe “pessoa” e o sentido da passagem. A identidade vem do telemóvel registado (opt-in), nunca da imagem. |
| **Nada é gravado** | Frames da stream analisados no edge e descartados em segundos; só saem eventos. |
| **Visitas protegidas** | Aviso à entrada (pictograma); as visitas só aparecem como um número. |
| **O senhorio não vê** | Nem imagens, nem entradas, nem horários: só totais mensais e alertas de segurança. |
| **A casa decide** | A câmara é votada pelos moradores; sem ela, a presença usa só Wi-Fi e sensor da porta. |

### 5.4 Uma câmara como uma campainha inteligente — mas sem gravar

Câmaras na entrada de casa já são comuns: campainhas inteligentes como a Ring detetam movimento, avisam quem chega e gravam vídeo. A nossa câmara faz menos do que isso: não grava, não mostra imagens a ninguém e só conta passagens na soleira. Funciona como um detetor de presença.

Numa casa arrendada há duas diferenças a respeitar: quem instala é o senhorio e quem passa são os inquilinos e as visitas. Por isso: a câmara é votada pela casa, há aviso à entrada, aponta só para dentro da casa (nunca para a rua, o patamar ou os vizinhos), o senhorio não tem acesso a nada e a base é o interesse legítimo de segurança, com avaliação de impacto antes do piloto. Assim fica mais protetora da privacidade do que uma campainha comum.

### 5.5 Acesso à imagem: stream RTSP

A imagem chega pela **stream RTSP** da câmara, lida localmente por OpenCV na máquina que corre a visão (`vision/source.py`). Os frames são analisados no edge e descartados; só os eventos (“entrou” / “saiu”) seguem para a base de dados. A stream não é guardada nem reencaminhada.

---

## 6 Casa justa: as regras e os motores

### 6.1 O que se mede, em produção e no MVP

| O que se mede | Como | Porquê |
|---|---|---|
| **Aquecedor de cada quarto** | Uma tomada com medição por quarto | É onde está o dinheiro (~360 kWh/mês num quarto com aquecedor). O que passa pela tomada do quarto da Ana é da Ana. |
| **Total do mês** | A fatura (foto, PDF ou MEO Energia) | Para dividir a conta não é preciso tempo real. |
| **Lâmpadas** | Estimativa: 9 W × tempo × brilho | A lâmpada não mede; são cêntimos (~0,22 €/mês). |
| **MVP da hackathon** | A única tomada que mede W fica à entrada da extensão | Faz de medidor do total da demo; o motor de assinaturas separa-o por aparelho. |

### 6.2 As três regras da divisão justa

Não tentamos saber quem gastou cada watt — seria impossível e invasivo. A casa segue três regras que toda a gente percebe:

| Regra | O que significa |
|---|---|
| **1. O teu quarto é teu** | Tudo o que passa pela tomada do teu quarto é teu. A ligação pessoa–quarto vem do contrato de arrendamento. |
| **2. As zonas comuns são de todos** | O que está na sala ou na cozinha vai para a conta da sala — mesmo que o aparelho seja de alguém. O que conta é onde o aparelho está, não de quem é. |
| **3. O sistema avisa do que não bate certo** | Aparelho pessoal fora do quarto, pico numa zona comum, orçamento a chegar ao limite. |

**Como se divide a conta da sala (a casa escolhe)**

| Opção | Como funciona |
|---|---|
| **A. Por igual** | O consumo da sala divide-se por todos. Simples. |
| **B. O bot pergunta** *(recomendada)* | Quando um aparelho grande liga fora de um quarto, o bot pergunta no grupo da casa (os 4 moradores + o bot): “O aquecedor do Bruno está ligado na sala. De quem é esta conta?” **[É minha] [É de todos]**. Numa casa onde as pessoas se entendem, um toque resolve. Sem resposta em 24 h → opção A ou C. |
| **C. Por quem está em casa** | Divide pelos que estão em casa segundo o motor de presença (6.8). Se só o João está em casa, conta para o João. |

O bot só pergunta quando vale a pena (por exemplo, acima de 0,50 €): uma chaleira de 2 cêntimos vai direto para a conta comum.

**A complexidade quase não muda o resultado**

| Pessoa | Por igual (hoje) | Três regras | Atribuição total por IA |
|---|---:|---:|---:|
| Ana (aquecedor) | 30,00 € | 46,80 € | 45,12 € |
| Bruno | 30,00 € | 27,60 € | 29,76 € |
| Carla | 30,00 € | 24,40 € | 24,64 € |
| Diogo | 30,00 € | 21,20 € | 20,48 € |

*Fatura de 120 € (24 € fixos + 600 kWh × 0,16 €). Três regras: quartos medidos, resto por igual. O grande salto está entre “por igual” e “cada um paga o seu quarto”; o resto é afinação (~2 € por pessoa).*

### 6.3 Motor de assinaturas: o processo

Responde a duas perguntas: o QUE foi ligado (pela assinatura) e ONDE está (num quarto ou numa zona comum). Só se a casa escolher “paga quem usa” para uma zona comum é que entra uma terceira pergunta — quem — respondida pelo motor de presença.

| Passo | O que faz | Tipo |
|---|---|---|
| 0. Registo | Cada pessoa liga os seus aparelhos e diz ao bot o que são e de quem. A chaleira é registada como “partilhada”. | Manual (uma vez) |
| 1. Deteção de degraus | Nas leituras de watts, encontra os momentos em que o consumo sobe ou desce de repente. | Algoritmo simples |
| 2. Identificar o aparelho | Compara cada degrau com as assinaturas registadas. | IA (machine learning) |
| 3. Localizar | A tomada de um quarto mudou? → quarto. Nenhuma tomada mudou mas o total subiu? → zona comum. | Algoritmo simples |
| 4. Aplicar a regra | Quarto → dono do quarto. Zona comum → conta da sala (A, B ou C). | Regras da casa |
| 5. Confirmar | Se houver dúvida, o bot pergunta. | Manual (um botão) |
| 6. Aprender | Cada confirmação melhora assinaturas e hábitos. | IA |
| 7. Explicar | Recibos explicados e respostas em português normal. | IA (LLM) |

### 6.4 Registo e assinaturas

Quando alguém entra na casa ou compra um aparelho, liga-o sozinho; o bot pergunta: “Liguei algo de ~1050 W. O que é e de quem?”. A assinatura guarda potência (±50 W), duração típica, padrão (ciclos de termóstato, descida de carga) e horário habitual.

| Aparelho | Dono | Potência | Padrão |
|---|---|---|---|
| Aquecedor | Ana | ~1050 W | Horas seguidas, ciclos de termóstato |
| Aquecedor | Bruno | ~2000 W | Contínuo, ao fim do dia |
| Secador | Bruno | ~600 W | 1–5 min, de manhã |
| Chaleira | Casa (partilhada) | ~2000 W | 2–4 min, desliga sozinha |
| Trotinete | Diogo | 120 W → 0 | Desce ao longo de ~2 h |
| PC | João | ~180 W | Variável; também serve de pista de presença |

O aquecedor do Bruno e a chaleira têm ~2000 W mas distinguem-se pela duração: o sistema espera pelo desligar (ou ~5 min) antes de decidir.

### 6.5 Exemplo: o aquecedor do Bruno na sala

```
18:02   porta: 1 entrada · telemóvel do João liga-se ao Wi-Fi     → em casa: João
18:05   total +2000 W, durante mais de 5 min                       → assinatura: aquecedor do Bruno
        tomada do quarto do Bruno: 0 W                             → não está no quarto: ZONA COMUM
        telemóvel do Bruno fora desde as 08:30                     → o Bruno não está em casa
18:06   regra da sala = B → bot: "O aquecedor do Bruno está ligado na sala. De quem é esta conta?"
18:07   João: [É minha]                                            → conta para o João
```

Com a opção C, o sistema atribuía-o diretamente ao João (único em casa, 97%). Com a opção A, ia para a conta da sala.

### 6.6 Aparelhos desconhecidos

Se um degrau que não corresponde a nada se repete (por exemplo, ~800 W todos os dias às 8h), o sistema agrupa sozinho os eventos parecidos (clustering) e pergunta uma vez: “Um aparelho de ~800 W liga todos os dias às 8h. O que é e de quem?” → “torradeira da Carla”.

### 6.7 Casos difíceis

| Caso | Solução |
|---|---|
| Dois aparelhos ao mesmo tempo | Cada aparelho tem um estado; um degrau novo soma-se; uma descida associa-se ao aparelho ligado com potência mais parecida. |
| O termóstato desliga a meio de outro uso | O sistema conhece os ciclos e associa o −1050 W ao aquecedor. |
| Dois quartos com aparelhos iguais | Cada quarto tem a sua tomada; com um só medidor, cruza temperatura dos quartos, presença e hábitos; se houver dúvida, pergunta. |
| Carregar coisas na sala para não pagar | Telemóvel e portátil “poupam” ~0,30 €/mês. Só o aquecedor vale a batota — e esse é reconhecido em qualquer tomada e cai na conta da sala, onde o bot pergunta. |
| Aparelhos pequenos (<100 W) | Não se distinguem bem; vão para o resíduo comum. São cêntimos. |

### 6.8 Motor de presença: saber quem está em casa sem olhar para ninguém

Serve para a conta da sala (opção C) e para a deteção de batota. Na fase 2, serve também os avisos de aparelhos esquecidos e o modo AWAY. Não é necessário para a fatura base — as regras 1 e 2 funcionam sem ele.

```
Contrato   →  João = quarto 3                         (ligação pessoa ↔ quarto)
João       →  registou o seu telemóvel no bot         (opt-in, feito por ele)
Telemóvel  →  ligado ao Wi-Fi da casa às 18:02        (pista forte de presença)
Câmara     →  "1 pessoa entrou às 18:02"              (só contagem, sem identidade)
PC do João →  ligou às 18:04                          (ação humana: confirma)
```

| Pista | Como funciona | Peso |
|---|---|---|
| Telemóvel no Wi-Fi | O router vê os telemóveis registados; em produção, o router MEO (ativo exclusivo da Altice) | Forte (presença) |
| Câmara na porta | Entradas e saídas, sem identidade | Forte quando coincide com outra pista |
| Aparelho pessoal a ligar | O PC do João liga → alguém o ligou | Forte (ação humana) |
| Atividade no quarto | Luz, tomada ou porta do quarto 3 | Média |
| Bot | “Cheguei” / “Estou fora até domingo”; ou etiqueta NFC na porta | Forte, mas voluntária |
| Rotina (opt-in) | Horário de aulas, hábitos aprendidos | Fraca |
| Produção (opcional) | Porta-chaves Bluetooth, radar de presença por quarto (sem imagem), fechadura com código pessoal | Forte |

**As regras que evitam erros**

| Problema | Como se resolve |
|---|---|
| Dados móveis / telemóvel a dormir | Presença no Wi-Fi conta muito; ausência conta pouco. Só se considera que alguém saiu se o telemóvel desaparecer 20–30 min e houver uma saída pela porta. |
| Programas a correr depois de sair | Um aparelho a continuar ligado não prova presença; só um aparelho a ligar prova. O consumo do PC continua a ser do João (é dele), mas não conta como “João em casa”. |
| Desligar o Wi-Fi para fingir que não está | Entrou alguém pela porta e um aparelho ligou, mas ninguém está “oficialmente” em casa → “consumo com presença por explicar” e o bot pergunta. As pistas seguintes (luz do quarto, PC) desmentem. |
| Quem não regista o telemóvel | Não perde nada: o bot pergunta quando precisa. Ter o telemóvel registado é a forma de provar que não estava em casa. |

Resultado por pessoa: **em casa / fora / incerto**. Se incerto, pergunta em privado: “João, estás em casa?”

### 6.9 Limites, picos e avisos

| Aviso | Gatilho | Para quem | Exemplo de mensagem |
|---|---|---|---|
| **Orçamento pessoal** | Cada pessoa define o seu limite mensal (ex.: 25 €). Avisos aos 50%, 80% e 100%, com previsão do fim do mês | Privado | “Já gastaste 20 € (80%). Ao ritmo atual vais chegar aos 31 €. O aquecedor é 70% disso.” |
| **Plafond do senhorio** | Despesas incluídas até X kWh por quarto; aviso antes de passar e quando passa | Privado | “Faltam 15 kWh para o teu plafond incluído. A partir daí pagas o excesso.” |
| **Pico na zona comum** | Potência numa zona comum acima de 1,5 kW durante mais de 30 min, ou conta da sala do dia acima de 2× a média | Grupo | “Pico na sala: 2 kW há 40 min (aquecedor do Bruno). De quem é esta conta?” |
| **Não bate certo** | Tomada do quarto a 0 W mas a assinatura do aparelho aparece no total; consumo noturno anormal | Grupo ou dono | “Há um aparelho igual ao aquecedor da Ana ligado fora do quarto dela.” |
| **Aparelho esquecido** *(fase 2)* | Aparelho grande a consumir com o dono fora de casa há mais de 1 h | Privado (dono) | “O teu aquecedor está ligado e saíste há 1 h. Queres que o desligue?” |
| **Casa vazia** *(fase 2)* | Todos saíram (porta + Wi-Fi) | Grupo | “Saíram todos. Alarme armado. A placa ficou desligada.” |

**Onde chegam:** no Telegram — no grupo da casa (os 4 moradores + o bot) ou em mensagem privada — como notificação no telemóvel; os avisos mais importantes também na lâmpada (âmbar a 80% do orçamento, vermelho a 100%). Cada pessoa escolhe os limites e o silêncio noturno.

### 6.10 Resumo: manual, algoritmo, estatística ou IA

| Tipo | Partes |
|---|---|
| **Manual** | Registar aparelhos e telemóvel (uma vez); responder “é minha?” quando há dúvida; definir orçamentos e regras da casa; votar a câmara |
| **Algoritmo** | Detetar degraus; localizar (quarto ou zona comum); somar e dividir a fatura; disparar avisos de limite e de pico |
| **Estatística e regras** | Fundir pistas de presença (pesos e tolerância a falhas); atribuir consumos não reclamados por evidência (bayesiano); prever a fatura e o orçamento (extrapolação); detetar anomalias (desvios ao perfil e regras de pico) |
| **IA — machine learning** | Reconhecer aparelhos pela assinatura; descobrir aparelhos desconhecidos (clustering) |
| **IA — visão** | Contar entradas e saídas na porta (sem identidade) |
| **IA — LLM** | Perceber respostas em português, explicar recibos, conversar no grupo, converter regras em cenários |

> **A frase para o júri:** “O teu quarto é teu, as zonas comuns são de todos, e o sistema avisa do que não bate certo. A IA reconhece cada aparelho pela assinatura em qualquer tomada, sabe quem está em casa sem olhar para ninguém e avisa antes de a conta chegar ao teu limite.”

---

## 7 O modelo de divisão justa

A fatura é decomposta em quatro partes, cada uma com uma regra de divisão votada pela casa:

| Componente | Como se mede | Como se divide (padrão) |
|---|---|---|
| **Parte fixa** (potência, taxas) | Lida da fatura pelo agente (visão). | Partes iguais (opção: ponderar pelos dias em casa). |
| **Consumo individual** | Tomada do quarto, lâmpada (W × tempo × brilho) e aparelhos partilhados atribuídos (zonas da câmara ou pergunta no bot). | 100% a quem consumiu. |
| **Consumo comum ponderado** | Aquecimento e luz da sala, via NILM + ocupação (se a casa ativar as zonas). | Proporcional às horas de ocupação. |
| **Resíduo** | Total da casa (fatura) − tudo o que foi atribuído: frigorífico, router, termoacumulador… | Partes iguais. |

### 7.1 Exemplo: casa de 4 estudantes, um mês de inverno

*Valores ilustrativos: fatura de 120 € = 24 € de parte fixa + 600 kWh × 0,16 €/kWh (impostos incluídos).*

| Pessoa | Quarto (kWh) | Sala (horas) | Sala (kWh) | Máq. (kWh) | Indiv. (kWh) | Igual | Conta Certa |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ana\* | 180 | 10 | 6 | 6 | 192 | 30,00 € | 45,12 € |
| Bruno | 60 | 40 | 24 | 12 | 96 | 30,00 € | 29,76 € |
| Carla | 40 | 30 | 18 | 6 | 64 | 30,00 € | 24,64 € |
| Diogo | 20 | 20 | 12 | 6 | 38 | 30,00 € | 20,48 € |
| **Total** | 300 | 100 | 60 | 30 | 390 | 120,00 € | 120,00 € |

\* Ana tem um aquecedor de 2 kW no quarto.

Resíduo = 600 − 390 = 210 kWh (33,60 €), dividido por igual, tal como a parte fixa (24 €). Cada pessoa paga 6 € + 8,40 € de base comum, mais o seu consumo individual a 0,16 €/kWh. Neste exemplo, 65% da energia da fatura é atribuída a alguém — e o recibo de cada pessoa diz isso explicitamente.

> **Plafond solidário.** Para que a divisão justa não incentive ninguém a passar frio, a casa define um plafond de aquecimento básico por quarto (por exemplo, os primeiros 30 kWh/mês de aquecimento de cada quarto) que é pago em comum. Só o consumo acima do plafond é individual. O sensor de clima deteta quartos que ficam várias noites abaixo de 18 °C e o agente avisa a pessoa, em privado, de que tem plafond por usar.

> **Bi-horário: a mesma regra, com preços diferentes.** Nos tarifários bi-horários a eletricidade é mais barata à noite (22h–08h) e ao fim de semana. A Conta Certa valoriza cada kWh ao preço da hora em que foi consumido e o agente sugere — e agenda com cenários — o uso de aparelhos nas horas de vazio. Quem muda o comportamento fica com a poupança.

---

## 8 À prova de batota

**A Conta Certa não depende da honestidade.** Nenhum sistema é 100% à prova de batota. O desenho garante duas coisas: **o pior caso nunca é pior do que a divisão igual de hoje**, e **a batota não compensa**.

### Camada 1 — O que vale dinheiro mede-se sem cooperação

O grande consumo de uma casa de estudantes é o aquecimento dos quartos, e esse é medido passivamente pela tomada do quarto. No exemplo da secção 7, **300 dos 390 kWh atribuídos (77%) vêm de medição passiva**. A parte que poderia depender de alguém se identificar é a máquina de lavar: 30 kWh, 4,80 € numa fatura de 120 € (4%). Fazer batota na chaleira vale cêntimos.

### Camada 2 — Sem identificação, o consumo não desaparece

Um consumo não reclamado é atribuído pelo motor de decisão (M3, por inferência bayesiana) a partir de evidência passiva: sensores de contacto nas portas dos quartos, contagem anónima da câmara, hora do dia e hábitos. Em produção, com opt-in, pode juntar-se a presença dos telemóveis na rede Wi-Fi do router MEO — um ativo que só a Altice tem. Se a evidência for ambígua, o consumo é dividido só por quem estava em casa, não por todos. Os inocentes que estavam em casa passam a ter interesse em contestar — a pressão social trabalha a favor da verdade.

### Camada 3 — A honestidade é a estratégia vencedora

| Comportamento | O que pagas |
|---|---|
| Dizes “é minha” quando o bot pergunta | Exatamente o que mediste. Nunca mais do que gastaste. |
| Não te identificas | O modelo atribui pela evidência, com a estimativa completa e sem desconto. Recusar não poupa dinheiro — só tira controlo sobre a atribuição. |

**E carregar coisas na sala ou na cozinha?**

| O que se carrega na sala | Por mês | Custo | O batoteiro “poupa” |
|---|---:|---:|---:|
| Telemóvel, todos os dias | ~0,4 kWh | ~0,06 € | ~0,05 € |
| Portátil, todos os dias | ~2 kWh | ~0,30 € | ~0,23 € |
| Trotinete, todos os dias | ~12 kWh | ~2 € | ~1,50 € |
| **Aquecedor de 1 kW, 4 h/dia** | ~120 kWh | **~19 €** | **~14 €** |

Só o aquecedor vale a batota — e o sistema atribui **por aparelho, não por tomada**: a assinatura do aquecedor da Ana é reconhecida em qualquer tomada da casa. Se a tomada do quarto marca 0 W, o medidor do total continua a ver os mesmos watts e o quarto arrefece, os sensores contradizem-se. Consumos sem dono aparecem no grupo sem acusar ninguém; abaixo de um limite combinado (por exemplo, 5 kWh/mês) são ignorados. Se o aquecedor na sala aquece toda a gente, a casa pode decidir dividi-lo por quem lá esteve.

### Camada 4 — Os sensores denunciam-se uns aos outros

A batota a sério não é na chaleira: é ligar o aquecedor de 2 kW numa tomada da sala com uma extensão. O sistema cruza fontes independentes — se uma mente, as outras contradizem-na:

| Tentativa de batota | Como é detetada | Consequência |
|---|---|---|
| Usar um aparelho partilhado sem dizer nada | Está numa zona comum: vai para a conta da sala; se for grande, há aviso de pico e o bot pergunta. | Conta da sala (por igual, por quem diz “é minha”, ou por presença). |
| Aquecedor ligado numa tomada comum ou diretamente na parede do quarto | O medidor do total vê uma carga contínua de 2 kW que não está em nenhuma tomada de quarto; ao mesmo tempo, o sensor de clima do quarto sobe 3 °C com a tomada do quarto a 0 W. | “Consumo não explicado, correlacionado com o quarto X” — imputado a esse quarto e visível no grupo. |
| Desligar o Wi-Fi para parecer fora de casa | A câmara conta uma entrada e um aparelho liga, mas ninguém está “oficialmente” em casa. | “Consumo com presença por explicar”; o bot pergunta; as pistas seguintes desmentem. |
| Tapar ou desligar a câmara | Deteção de câmara obstruída ou offline (stream RTSP interrompida), comunicada ao grupo. | Modo conservador: consumo não explicado dividido pelos presentes. |
| Desligar a tomada inteligente do quarto | A tomada fica offline no MCP; o medidor do total continua a ver consumo e o clima do quarto continua a subir. | Alerta ao grupo; consumo imputado ao quarto por inferência. |

---

## 9 Os modelos de IA

> **Princípio:** IA onde acrescenta valor, regras e estatística onde chegam — e dizemo-lo ao júri. Os componentes organizam-se em três camadas: **perceção**, **decisão** e **interface**. Só M1, M2 e M4 são IA no sentido de modelos que aprendem ou geram; M3 é código.

| Camada | Componente | Abordagem | Para quê | Tipo | MVP |
|---|---|---|---|---|:-:|
| Perceção | **M1 Entradas e saídas** | YOLO leve (classe “pessoa”) + linha virtual na soleira da porta, sobre a stream RTSP, no edge | Presença e contagem de visitas | IA — visão (modelo pré-treinado) | ✔ |
| Perceção | **M2 Assinaturas (NILM)** | Deteção de degraus + classificação por potência, duração e padrão (vizinho mais próximo); clustering de desconhecidos; aprende com confirmações | Reconhecer aparelhos em qualquer tomada | IA — machine learning simples | ✔ |
| Decisão | **M3 Motor de decisão** | Quatro funções sobre a mesma tabela de eventos, sem modelo treinado: **(a) presença** — fusão de pistas (Wi-Fi, porta, aparelhos a ligar, bot) com pesos e tolerância a falhas; **(b) atribuição** — consumo não reclamado repartido por evidência (inferência bayesiana); **(c) orçamento e previsão** — média por hora do dia + extrapolação linear até ao fim do mês; **(d) anomalias** — desvios ao perfil, regras de pico nas zonas comuns, “não bate certo” entre tomadas e total | Conta da sala (opção C), batota, avisos aos 50/80/100%, previsão da fatura, avisos de pico | Estatística e regras (código) | ✔ |
| Interface | **M4 Agente LLM + MCP** | LLM com ferramentas: MCP (ler e agir) + próprias (consumo, recibo, orçamento, quem está em casa); lê faturas por visão | A interface: conversa, explica, pergunta, age | IA — LLM | ✔ |

**Exemplo completo de M2 + M3 + M4 a funcionar juntos:** o aquecedor do Bruno na sala, na secção 6.5.

**Fase 2:** aparelhos esquecidos e modo AWAY entram no M3 mais tarde (ver 19.2).

> **Guarda-corpos do agente.** O agente nunca inventa números: tudo vem de ferramentas e as contas são feitas em código. Ações sensíveis (desarmar a segurança, cortar aparelhos fora das regras votadas) pedem confirmação humana.

---

## 10 Privacidade e enquadramento legal

*Resumo do raciocínio de desenho com base no RGPD. Não é aconselhamento jurídico: antes de um piloto, validar com um jurista ou DPO.*

### 10.1 Porque é que “sujeito a gravações” no contrato não serve

O consentimento só é válido se for livre — a pessoa tem de poder recusar sem desvantagem — e não pode ser condição de um contrato para algo que não é necessário. Um estudante numa crise de habitação, perante “aceitas ou não tens casa”, não escolhe livremente. E a cozinha e a sala são a casa de quem lá vive: até num prédio, câmaras em partes comuns exigem o consentimento unânime dos condóminos (DECO).

### 10.2 Bases legais por função

| Função | Base legal proposta | Porquê |
|---|---|---|
| Consumo por quarto (tomadas, sensores) | **Execução do contrato** | O contrato prevê a divisão por consumo; medir é necessário para o cumprir. |
| Casa vazia e modo AWAY *(fase 2)* | **Interesse legítimo** (proteção de pessoas e bens) | Segurança contra intrusão; sem gravação; sinalização obrigatória. |
| Câmara na porta (contagem) | **Interesse legítimo** (segurança) + votação da casa | Só conta passagens na soleira; nada gravado; aviso à entrada; visitas só como número. |
| Presença pelo Wi-Fi | **Consentimento** (opt-in de cada inquilino) | Quem não regista o telemóvel não perde nada: o bot pergunta quando precisa. |

### 10.3 A ligação pessoa–quarto e a energia

A ligação vem do **contrato de arrendamento** (quarto n.º, pessoa, datas): o sistema não adivinha quem é quem. O Código Civil (art. 1078.º) deixa as partes estipular por escrito o regime de encargos e despesas. Casos: casal no mesmo quarto (divide entre si); saída a meio do mês (leitura na data da troca); visitas (contam para quem as recebe). O senhorio só pode **repartir o custo real** da fatura — vender eletricidade é uma atividade regulada. O senhorio vê totais mensais por quarto, nunca curvas horárias nem presença.

### 10.4 Cláusula proposta para o contrato

> “A eletricidade é repartida segundo o consumo medido em cada quarto, através do serviço Conta Certa, com um plafond solidário de [X] kWh mensais por quarto pago em comum; o consumo das zonas comuns é repartido segundo as regras votadas pelos moradores. Na porta de entrada existe um sensor ótico que conta entradas e saídas, sem gravar imagens nem identificar pessoas. O registo do telemóvel na rede da casa é opcional e pode ser retirado a qualquer momento. Cada morador pode consultar, exportar e contestar os seus dados. O senhorio reparte apenas o custo real da fatura.”

### 10.5 O que nunca acontece e o que é obrigatório

**Nunca:** reconhecimento facial, gravação contínua, câmaras em quartos e casas de banho; o senhorio ver quem está em casa ou imagens; venda de dados.
**Antes do piloto:** avaliação de impacto (AIPD), aviso com pictograma, registo de tratamentos, prazos de conservação definidos com o DPO, direitos de acesso e contestação pelo próprio bot.

---

## 11 Facilidade de adoção

O maior obstáculo é quem perde dinheiro com a divisão justa. Por isso o produto é adotado pelo senhorio, antes de os inquilinos entrarem — e cada parte tem razões para aceitar.

| Quem | O que ganha | Porque aceita |
|---|---|---|
| **Senhorio** | Fim do risco das despesas incluídas, menos conflitos, alertas de segurança e de consumo, recibos que ninguém contesta. | Paga-se em poucos meses de inverno (secção 15) e diferencia o anúncio. |
| **Inquilino que gasta pouco** | Deixa de pagar a conta dos outros: no exemplo, 20,48 € em vez de 30 € (−32%). | Benefício direto. |
| **Inquilino que gasta muito** | Previsibilidade, previsão da fatura, horas de vazio, plafond solidário para o básico. | Escolheu a casa a saber as regras; sem risco de abusos, a renda não precisa de ser inflacionada. |
| **Todos** | Avisos que poupam dinheiro (orçamento, picos) e uma casa mais atenta. | Valor que não depende de quem gasta mais. |

### 11.1 Barreiras e respostas

| Barreira | Resposta |
|---|---|
| Medo da câmara | Nunca grava nem reconhece caras; só conta entradas e saídas na porta; votada pela casa. |
| Custo | Comodato na mensalidade; o equipamento fica na casa entre inquilinos. |
| Mais uma app / instalação | Sem app nova: grupo de mensagens e cor da lâmpada. Dispositivos sem fios e sem obras. |
| Desconfiança nos números | Cada recibo mostra o que é medido e o que é estimado, e tem um botão para contestar. |
| Batota | Medição passiva e sensores cruzados; o pior caso é a divisão igual de hoje. |

### 11.2 Adoção por camadas

| Nível | Equipamento | O que entrega |
|---|---|---|
| **1 · Base** | Tomada, lâmpada e sensores em cada quarto + detetor de fumo | Aquecedores medidos, três regras, orçamento e avisos. |
| **2 · Presença** | + câmara na porta + telemóveis registados | Conta da sala por presença; (fase 2) aparelhos esquecidos e AWAY automático. |

---

## 12 A experiência: conversas com a casa

A Conta Certa não pede a ninguém que instale mais uma app: vive no grupo onde a casa já fala. O **grupo da casa** tem os 4 moradores e o bot; é aí que o bot faz as perguntas (“de quem é esta conta?”), manda os avisos de pico e abre as votações. Os avisos pessoais (orçamento, plafond) vão por mensagem privada.

**Regra a atuar em tempo real**

> **Conta Certa:** 🪟 A janela do quarto da Ana está aberta há 5 min com o aquecedor ligado. Desliguei-o (regra #3, votada a 2/11). Volto a ligá-lo quando a janela fechar.

**Disputa resolvida com dados**

> **Bruno:** Porque é que pago mais 5 € que a Carla este mês?
>
> **Conta Certa:** Diferença de 5,12 €, explicada por três coisas:
> • Quarto: 60 kWh vs 40 kWh (+3,20 €)
> • Sala: estiveste 40 h, a Carla 30 h (+0,96 €)
> • Máquina de lavar: 12 kWh vs 6 kWh (+0,96 €)
> `[Ver recibo]` `[Ver dados]`

**Conta da sala: o bot pergunta (no grupo)**

> **Conta Certa:** ⚡ O aquecedor do Bruno está ligado na sala há 20 min (~2 kW). O Bruno não está em casa. De quem é esta conta? `[É minha]` `[É de todos]`
>
> **João:** É minha
>
> **Conta Certa:** Registado na tua conta (0,64 € até agora). O Bruno não paga o que não usou.

**Orçamento pessoal (mensagem privada)**

> **Conta Certa · privado:** João, já gastaste 20 € dos teus 25 € deste mês (80%). Ao ritmo atual chegas aos 31 €. O aquecedor na sala é 70% disso. Queres que o desligue às 23h? `[Sim, às 23h]` `[Não]`

**Plafond solidário (mensagem privada)**

> **Conta Certa · privado:** Olá Diogo. O teu quarto esteve abaixo de 16 °C em 4 noites esta semana. Ainda tens 28 kWh do plafond solidário este mês — não pagas nada por eles. Queres que ligue o aquecedor às 22h nas horas de vazio? `[Sim, às 22h]` `[Não, obrigado]`

**Resumo semanal no grupo**

> **Conta Certa:** 📊 Semana 46: a casa gastou 132 kWh (−9% face à semana passada). 71% atribuídos a alguém. 3 regras atuaram (2× janela aberta, 1× corte das 3h). 🏆 Na Liga das Casas da UA estamos em 4.º. Previsão da fatura deste mês: 112–121 €.

**Regra nova escrita em português**

> **Carla:** Proponho: aquecedores desligam às 3h se ninguém mexeu em nada há uma hora
>
> **Conta Certa:** Proposta #7 — “Corte das 3h”: todos os dias às 03:00, se não houver atividade há 60 min, desligar as tomadas dos aquecedores. Exceção: quartos abaixo de 16 °C. Votem 👍/👎 até amanhã às 20h.
>
> **Conta Certa:** ✅ Aprovada (3/4). Cenário “Corte das 3h” criado e ativo.

### Fase 2 — cenas de saída de casa (ficam para depois)

**Saíste com um aparelho ligado (mensagem privada)**

> **Conta Certa · privado:** Saíste de casa há 1 h e o aquecedor que usavas na sala continua ligado. Desligo? `[Desliga]` `[Deixa estar]`

---

## 13 Use cases fora da caixa

O mesmo motor — medir, atribuir, explicar, agir — resolve problemas muito para lá da casa de estudantes.

| # | Use case | O que faz |
|---|---|---|
| 1 | **Quartos arrendados a estudantes** *(núcleo)* | O senhorio instala; os inquilinos sabem as regras desde o anúncio. Justa, segura e saudável. |
| 2 | **“Despesas incluídas com plafond justo”** *(senhorios)* | O senhorio oferece despesas incluídas até X kWh por quarto; o excedente paga quem o consome. Preço do quarto mais baixo e fim dos abusos. |
| 3 | **Trotinetes e bicicletas elétricas** *(câmara · IA)* | Carregar a trotinete em casa: cada bateria tem uma assinatura de carga (quem carrega paga, ou vai para a conta da sala se estiver numa zona comum) e a tomada corta quando a potência cai (bateria cheia). |
| 4 | **Despesas incluídas sem abusos** | O senhorio inclui até X kWh por quarto e o excedente paga quem o consome; avisos antes de passar o plafond. |
| 5 | **Residências universitárias** *(universidades)* | Consumo por quarto, orçamentos e avisos em escala. Aveiro, onde decorre o Aveiro Tech City Hackathon, é o piloto natural. |
| 6 | **Alojamento Local** *(câmara)* | Energia por estadia, transparente para o hóspede; o ar condicionado desliga com a janela aberta; contagem anónima de pessoas na entrada face à reserva (festas, sobrelotação) — só números, nunca caras. |
| 7 | **Termómetro social** *(IA)* | Com opt-in: idosos ou pessoas vulneráveis em quartos arrendados. Se o quarto fica dias abaixo de 18 °C ou se não há atividade, a família ou a junta de freguesia recebe um aviso. A pobreza energética passa a ser detetável. |
| 8 | **Comunidades de energia** *(energia)* | O mesmo motor divide a produção solar partilhada entre apartamentos ou frações em autoconsumo coletivo, de forma explicável. |
| 9 | **Liga das Casas** *(gamificação)* | Competição de poupança entre casas de estudantes de uma cidade ou universidade, patrocinada pela MEO. A poupança da casa vai para um “mealheiro” comum (o jantar da casa). |
| 10 | **Selo “Casa Justa”** *(mercado)* | Quartos com divisão justa certificada ganham um selo nos anúncios. Transparência para quem procura quarto, vantagem para bons senhorios. |
| 11 | **Laboratórios e coworkings** *(câmara)* | Check-in QR no equipamento (impressora 3D, forno de laboratório): energia por projeto ou grupo de investigação, sem contadores dedicados. |
| 12 | **Pais à distância** *(famílias)* | Com consentimento do estudante: relatório mensal com o consumo e o conforto do quarto (temperatura). Sem câmara e sem localização — tranquilidade sem vigilância. |

---

## 14 Impacto no mundo real

| Dimensão | Impacto | Como medimos |
|---|---|---|
| **Social** | Menos conflitos; contas que todos aceitam porque são explicáveis. | Disputas por mês; inquérito antes e depois. |
| **Económico** | Quem consome pouco deixa de subsidiar quem consome muito; o senhorio deixa de absorver abusos. | Diferença face à divisão igual; % atribuída. |
| **Ambiental** | Incentivo a poupar; a literatura sobre feedback direto (Darby, Oxford, 2006) reporta poupanças típicas de 5% a 15%. | kWh por casa face ao período base. |
| **Conforto** | Plafond solidário contra o frio; aviso privado a quem passa frio. | Horas abaixo de 18 °C nos quartos. |
| **Segurança** *(fase 2)* | Casa vazia armada sozinha; aparelhos esquecidos desligados. | Aquecedores desligados com a casa vazia; alertas reais. |

| ≥ 65% | < 10 s | 100% | 0 |
|---|---|---|---|
| da energia da fatura atribuída a uma pessoa | entre abrir a janela e o corte do aquecedor | da fatura repartida, sem margem para o senhorio | imagens gravadas |

*Metas de desenho para validar no piloto, não resultados já medidos.*

---

## 15 Viabilidade e sustentabilidade

### 15.1 Técnica: o que está provado e o que falta

| Componente | Estado | Risco e plano |
|---|---|---|
| Ler e agir via MCP | Documentado | Baixo; confirmar a frequência de atualização da tomada. |
| Imagem da câmara | Stream RTSP (decidido) | Baixo; confirmar fps e latência na hora zero. |
| Contagem na porta | Técnica conhecida | Baixo; afinar a linha da soleira. |
| Presença por Wi-Fi | Técnica conhecida | Médio; telemóveis a dormir → tolerância de 20–30 min. |
| NILM num só medidor | Funciona para cargas grandes | Médio; aparelhos com potências bem distintas. |

### 15.2 Custo do equipamento (preços de retalho de referência)

| Dispositivo | Preço | Quantidade | Subtotal |
|---|---:|---|---:|
| Tomada com medição | 9,90 € | 1/quarto | 9,90 € |
| Lâmpada RGB | 9,90 € | 1/quarto | 9,90 € |
| Sensor de porta/janela | 11,90 € | 1/quarto | 11,90 € |
| Sensor de temperatura e humidade | 7,90 € | 1/quarto | 7,90 € |
| **Por quarto** | | | **39,60 €** |
| Câmara interior | 38,90 € | 1/casa | 38,90 € |
| **Casa de 4 quartos** (sem gateway nem detetor) | | | **197,30 €** |

### 15.3 Valor para o senhorio

Num quarto com despesas incluídas e aquecedor 6 h por noite (~360 kWh/mês), com um plafond de 30 kWh, o excesso é de 330 kWh × 0,16 € = 52,80 €/mês. O equipamento de uma casa de 4 quartos paga-se em menos de 4 meses de inverno com um único quarto nessa situação.

### 15.4 Modelo de receitas

| Segmento | Oferta | Valor para a Altice |
|---|---|---|
| **Senhorios e residências** (principal) | Subscrição por quarto com kit em comodato. Hipótese a validar: [2–3 €] por quarto/mês. | Receita recorrente; contratos multi-imóvel. |
| **MEO Energia** | Desconto se a casa aderir; a fatura entra automaticamente. | Aquisição: 50 mil clientes de energia em 2024, meta de duplicar. |
| **Universidades e municípios** | Residências; painel anónimo de pobreza energética (opt-in). | Escala e imagem social. |

*Referência: a MEO já comercializou um serviço Smart Home com mensalidade de serviço (7,50 €/mês) mais prestação dos equipamentos (5,56 €/mês durante 36 meses).*

### 15.5 Sustentabilidade

**Ambiental:** incentivo à poupança, horas de vazio, energia verde via MEO Energia. **Social:** plafond solidário, menos conflitos. **Económica:** receita recorrente, equipamento reutilizado entre inquilinos. **Legal:** conforme ao RGPD desde o desenho.

---

# PARTE B — PLANO DE DESENVOLVIMENTO

## 16 Arquitetura do MVP

```
Kit Connected Home                         Motores                      agent/
(tomada W · lâmpada · contacto · clima     energy/ · presence/          LLM + ferramentas
 · detetor de fumo · gateway 4G)           rules/ · billing · alerts/   MCP + próprias
        │                                          ▲                           │
        ▼                                          │                           ▼
 MCP Connected Home ─► collector/ (polling 3–5 s) ─┤                     Telegram
                                                   │                     grupo da casa:
 Câmara na porta (stream RTSP) ─► vision/ (edge) ──┤                     4 moradores + bot
   porta: entrou/saiu                              │
                                                   ▼                     dashboard/
 Telemóveis no Wi-Fi (hotspot) ─► presence/ ─► events.db (SQLite)        Streamlit
                                                   ▲
 Fatura (foto / PDF / MEO Energia) ─► agent/ (leitura)

 Ações via MCP: tomada · lâmpada · cenários
```

*Figura 1 — Arquitetura do MVP. Todos os módulos comunicam através de uma tabela de eventos em SQLite, o que permite à equipa trabalhar em paralelo.*

### 16.1 Tecnologias

| Parte | Tecnologia sugerida |
|---|---|
| Linguagem | Python 3.11 para tudo (uma só linguagem para 4 pessoas) |
| MCP | SDK MCP oficial em Python como cliente (confirmar o fluxo OAuth na hora zero) |
| Visão | `opencv-python` (leitura da stream RTSP), `ultralytics` (YOLO para pessoas na porta) |
| Faturas | LLM multimodal (foto ou PDF da fatura → JSON) |
| Agente | LLM com tool calling; ferramentas MCP + funções próprias |
| Bot | `python-telegram-bot`; um grupo de Telegram com as 4 pessoas + o bot |
| Dados | SQLite (`events.db`) + CSV com um mês simulado dos outros quartos |
| Dashboard | `streamlit` |

---

## 17 Repositório, módulos e contrato de eventos

### 17.1 Estrutura

```
conta-certa/
├── config.yaml              # quartos, pessoas (do contrato), telemóveis registados, IDs, limites
├── collector/
│   ├── mcp_client.py        # OAuth; listar dispositivos; ler detalhes; mudar capacidades
│   └── poller.py            # a cada 3–5 s: tomada, contacto, clima → events
├── vision/
│   ├── source.py            # fonte de imagem: stream RTSP (OpenCV)
│   └── door.py              # YOLO pessoa + linha na soleira → "entrou" / "saiu"
├── presence/
│   ├── wifi.py              # telemóveis registados ligados à rede (hotspot no MVP)
│   └── fusion.py            # junta Wi-Fi + porta + aparelhos + bot → em casa / fora / incerto
├── energy/
│   ├── steps.py             # deteção de degraus no total (ΔW, início, fim)
│   ├── signatures.py        # registo de aparelhos; classificação; clustering de desconhecidos
│   ├── locate.py            # quarto (tomada do quarto mudou) ou zona comum
│   └── billing.py           # três regras + conta da sala (A/B/C) + recibos
├── alerts/
│   ├── budget.py            # orçamento pessoal e plafond: 50/80/100% + previsão
│   └── peaks.py             # picos em zonas comuns; "não bate certo"
├── rules/engine.py          # janela aberta → corte; regras votadas
├── agent/
│   ├── tools.py             # consumo(), recibo(), explicar(), orcamento(), quem_esta() + MCP
│   └── bot.py               # Telegram (grupo: 4 moradores + bot): avisos, "de quem é esta conta?", registo, votos
├── dashboard/app.py         # Streamlit: total ao vivo, eventos, presença, recibos
├── data/events.db · data/simulated_month.csv
└── scripts/demo_reset.py
```

### 17.2 Contrato de eventos

Todos os módulos escrevem e leem uma tabela `events(ts, source, type, room, data_json)`:

```json
{"ts":"…18:02:01","source":"camera","type":"door","room":"entrada","data":{"dir":"in"}}
{"ts":"…18:02:05","source":"wifi","type":"phone_seen","room":"casa","data":{"person":"joao"}}
{"ts":"…18:02:06","source":"presence","type":"presence","room":"casa","data":{"joao":"in","bruno":"out","p":0.97}}
{"ts":"…18:05:10","source":"energy","type":"power_step","room":"casa","data":{"delta_w":2010}}
{"ts":"…18:10:10","source":"energy","type":"appliance","room":"sala","data":{"name":"aquecedor","owner":"bruno","zone":"comum"}}
{"ts":"…18:10:11","source":"alerts","type":"common_peak","room":"sala","data":{"w":2010,"min":5}}
{"ts":"…18:11:00","source":"bot","type":"claim","room":"sala","data":{"person":"joao","appliance":"aquecedor"}}
{"ts":"…21:00:00","source":"alerts","type":"budget","room":"quarto_3","data":{"person":"joao","pct":80,"forecast_eur":31}}
```

*Porquê assim: cada pessoa testa o seu módulo sozinha com eventos falsos; a integração é ligar tudo à mesma base de dados.*

---

## 18 Montagem da bancada de demo

```
Parede → Tomada Altice (mede W) = "medidor do total"
            └→ Extensão
                 ├─ Aquecedor do Bruno (mínimo, ~1000 W) → levado para a "sala"
                 ├─ Secador do Bruno (modo baixo, ~600 W)
                 └─ Chaleira da casa (~2000 W)           → "cozinha"
Parede → Candeeiro com a lâmpada RGB do kit (fora da extensão)
```

- Porta de cartão com o sensor de contacto; a câmara virada para ela, pelo lado de “dentro”, com o resto da imagem (stream RTSP) tapado a preto no ecrã.
- Hotspot do portátil: os telemóveis da equipa ligados a ele são a “rede da casa”; desligar o Wi-Fi = sair de casa.
- Sensor de clima perto do aquecedor (confirma o aquecimento).

| Cuidado | Porquê e como |
|---|---|
| Limite da tomada (~3,6 kW) | Nunca ligar os três aparelhos ao mesmo tempo; aquecedor + chaleira ≈ 3 kW. |
| Potências distintas | Medir os aparelhos antes; cada degrau com mais de 300 W de diferença. |
| Atualização do MCP | Se a tomada demorar mais de 10 s a atualizar, cada aparelho fica ligado pelo menos 2 min. |
| Corte da tomada | Corta a extensão inteira: fazê-lo no fim e dizer “em produção cada quarto tem a sua tomada”. |

---

## 19 Plano de 2 dias por pessoa

| Bloco | P1 · MCP e energia | P2 · Visão e presença | P3 · Agente e bot | P4 · Alertas, dados, pitch |
|---|---|---|---|---|
| **Dia 1 manhã** | Hora zero. Cliente MCP com OAuth; ler a tomada; medir a latência. | Ligar à stream RTSP; hotspot e deteção de telemóveis. | Bot Telegram e grupo da casa (4 pessoas + bot); esquema de eventos; `consumo()` com dados falsos. | Lançar o inquérito; `simulated_month.csv`. |
| **Dia 1 tarde** | `poller.py`; `steps.py`; registo de aparelhos pelo bot. | `door.py` (linha na soleira → entrou/saiu); `wifi.py`. | Agente LLM com ferramentas próprias e MCP (ler, mudar a lâmpada). | `budget.py` (orçamento 50/80/100% + previsão); montar a bancada. |

**Fim do dia 1 — pronto quando:** o dashboard mostra o total ao vivo, os degraus, as entradas/saídas e quem está em casa; o bot responde no grupo.

| Bloco | P1 · MCP e energia | P2 · Visão e presença | P3 · Agente e bot | P4 · Alertas, dados, pitch |
|---|---|---|---|---|
| **Dia 2 manhã** | `signatures.py` + `locate.py`; regra janela → corte via MCP. | `fusion.py` (em casa / fora / incerto; tolerância de 20–30 min). | Fluxos: “de quem é esta conta?”, avisos privados, “porque pago mais?”. | `peaks.py` (pico na sala); `billing.py` com as três regras. |
| **Dia 2 tarde** | Integração; `demo_reset.py`. | Afinar a linha da porta; registo “o que sai da câmara”. | Regra escrita pelo júri → cenário MCP. | Slides com o inquérito; guião; ensaio ×2. |

**Fim do dia 2 — pronto quando:** a demo da secção 22 corre duas vezes seguidas sem intervenção manual.

**Dia 3:** ensaio cronometrado ×3; vídeo de plano B; congelar o código; estudar as perguntas da secção 23.

### 19.1 O que cortar se o tempo apertar (por esta ordem)

1. Regra escrita pelo júri ao vivo.
2. Previsão do fim do mês (fica só o aviso por percentagem).
3. Opção C da conta da sala (fica a B: o bot pergunta).

**Nunca cortar:** motor de assinaturas + três regras, câmara na porta + Wi-Fi (presença), orçamento com aviso, pico na zona comum, regra janela → corte e o agente no grupo.

### 19.2 Fica para depois (fase 2)

As cenas que dependem de alguém **sair de casa** ficam fora do MVP, da demo e dos testes:

- **Aparelho esquecido ao sair:** “Saíste de casa há 1 h e o aquecedor continua ligado. Desligo?” (aviso privado + corte via MCP).
- **Casa vazia:** modo AWAY, alarme armado, alerta de entrada com a casa vazia e partilha do alarme de fumo com o senhorio.

O que **fica** no MVP: o motor de presença (em casa / fora / incerto), porque a opção C da conta da sala e a deteção de batota dependem dele.

---

## 20 Hora zero: verificações e planos B

Antes de escrever código de produto, responder a estas perguntas. Cada uma decide um ramo do plano.

| # | Verificação | Como testar | Se falhar |
|---|---|---|---|
| 1 | Autenticar no MCP a partir de um script | Cliente Python com OAuth; listar dispositivos | Usar um cliente MCP que já funcione (o do guia) e expor os dados ao resto por ficheiro ou HTTP local |
| 2 | A tomada devolve W? Com que atraso? | `GET_DEVICE_DETAILS` com a chaleira ligada/desligada; cronometrar | Se o atraso for > 10 s: aparelhos ligados ≥ 2 min na demo. Se não devolver W: potência nominal × estado |
| 3 | Stream RTSP da câmara | Abrir o URL RTSP com OpenCV ou `ffplay`; medir fps e atraso | Ensaiar a pipeline com um vídeo gravado enquanto se resolve |
| 4 | Cenários aceitam sensores como gatilho? | Cenário de teste “contacto abre → tomada desliga” | A regra corre no `rules/engine.py` e age via `UPDATE_DEVICE_CAPABILITIES` |
| 5 | O sensor de clima atualiza com que frequência? | Aquecedor ligado perto do sensor; cronometrar | Ligar o aquecedor mais cedo no guião |
| 6 | O portátil deteta os telemóveis no hotspot? | Ligar e desligar o Wi-Fi de um telemóvel; ver quanto tempo demora a detetar | Botão “cheguei / saí” no bot |

---

## 21 Testes e ensaio

| ✓ | Teste | Critério de aceitação |
|---|---|---|
| ☐ | Ligar cada aparelho sozinho | Degrau certo detetado e etiquetado |
| ☐ | Aquecedor do Bruno ligado fora do quarto dele | “Zona comum” + pergunta “de quem é esta conta?” no grupo |
| ☐ | Entrar pela porta com o Wi-Fi ligado | “1 entrada” + “Em casa: João” em < 30 s |
| ☐ | Telemóvel a dormir 10 min, sem passar a porta | Continua “em casa” |
| ☐ | Sair pela porta e desligar o Wi-Fi | “Fora” ao fim da tolerância |
| ☐ | Entrar com o Wi-Fi desligado e ligar um aparelho | “Consumo com presença por explicar” + pergunta |
| ☐ | Orçamento pessoal a 80% | Aviso privado com previsão + lâmpada âmbar |
| ☐ | 2 kW na sala durante 30 min | Aviso de pico no grupo, com o aparelho identificado |
| ☐ | Abrir a janela de cartão com o aquecedor ligado | Corte via MCP e mensagem em < 10 s |
| ☐ | “Porque é que a Ana paga mais?” | Resposta só com números das ferramentas |
| ☐ | Wi-Fi da sala a falhar | Hotspot de telemóvel + vídeo de plano B |
| ☐ | `demo_reset.py` | Estado limpo em < 1 min |

---

## 22 Guião da demo de 3 minutos

| Tempo | O que acontece | O que o júri vê |
|---|---|---|
| 0:00 | O problema: “120 € ÷ 4 = 30 € para todos — mas a Ana tem um aquecedor.” A casa é de um senhorio que usa a Conta Certa; as três regras no ecrã. | Problema e regras simples. |
| 0:25 | O “João” liga o Wi-Fi do telemóvel e entra pela porta de cartão → a câmara (stream RTSP) conta “1 entrada” → o ecrã mostra “Em casa: João”. A imagem da câmara aparece tapada a preto, só com a soleira. | Presença sem caras. |
| 0:55 | O João liga o aquecedor do Bruno na “sala” → o motor reconhece a assinatura, vê que não está no quarto do Bruno → “zona comum”. O bot pergunta no grupo da casa: “De quem é esta conta?” → o João carrega em “É minha”. | **WOW:** o aparelho é do Bruno, mas paga quem o usa. |
| 1:30 | Liga-se também a chaleira → pico na sala → aviso ao grupo. O João recebe em privado: “Já gastaste 80% do teu orçamento. Ao ritmo atual chegas aos 31 €.” A lâmpada fica âmbar. | Limites e picos. |
| 2:00 | “Porque é que a Ana paga mais?” → recibos dos 4 (2 simulados). Painel do senhorio: só totais por quarto. | Justo para todos, privado para cada um. |

> **Frase de fecho:** “O teu quarto é teu, as zonas comuns são de todos, e a casa avisa antes de a conta doer. A câmara não sabe quem és — só sabe que alguém entrou.”

---

# PARTE C — PREPARAR A APRESENTAÇÃO

## 23 Perguntas difíceis do júri

| Pergunta | Resposta curta |
|---|---|
| Não é complicado demais? | As regras são três e cabem numa frase: o teu quarto é teu, as zonas comuns são de todos, o sistema avisa. A complexidade fica dentro do sistema, não para quem lá vive. |
| E se alguém fizer batota? | O que vale dinheiro mede-se sem cooperação; os sensores verificam-se entre si; o pior caso é a divisão igual de hoje. |
| Uma câmara na porta não é vigilância? | Só vê a soleira (o resto fica a preto), só conta passagens, nunca grava nem reconhece caras. Quem é vem do telemóvel registado por opção. E é votada pela casa. |
| Uma câmara na entrada é legal? | Câmaras na entrada de casa já são comuns (campainhas como a Ring). A nossa faz menos: não grava, só conta passagens, aponta só para dentro, é votada pela casa, tem aviso à entrada e o senhorio não lhe acede. A validar com um jurista antes do piloto. |
| É legal? | Bases legais separadas por função; nada de “gravações” no contrato; AIPD e DPO antes do piloto. |
| Ler o contador com uma câmara não é prático? | Não o fazemos: em produção, tomada por quarto; o total do mês vem da fatura. |
| A lâmpada não mede consumo. | Estimamos: 9 W × tempo × brilho — cêntimos por mês. O dinheiro está no aquecedor, medido pela tomada. |
| E se carregarem coisas na sala ou na cozinha? | Telemóvel e portátil “poupam” ~0,30 €/mês. Só o aquecedor vale a batota — e cai na conta da sala, com aviso de pico e pergunta do bot. |
| E se alguém usar dados móveis? | Presença no Wi-Fi conta muito, ausência conta pouco: só se considera que saiu passados 20–30 min e com saída pela porta. Contradições (entrada + aparelho a ligar sem ninguém “em casa”) geram uma pergunta. |
| E se deixar o PC a correr depois de sair? | O consumo é dele (aparelho pessoal), mas um aparelho a continuar ligado não prova presença — só um aparelho a ligar prova. |
| Posso definir quanto quero gastar? | Sim: orçamento pessoal com avisos aos 50/80/100% e previsão do fim do mês; o senhorio pode definir um plafond por quarto. |
| E se eu usar o aquecedor do meu colega na sala? | O que conta é onde o aparelho está, não de quem é: fora do quarto dele vai para a conta da sala e o bot pergunta “de quem é esta conta?”. Carregas em “é minha” — o teu colega não paga o que não usou. |
| Onde é que isto é mesmo IA? | Em três sítios: a visão na porta (YOLO), o reconhecimento e a descoberta de aparelhos pela assinatura (machine learning) e o agente LLM. Presença, previsão e anomalias são estatística e regras; detetar degraus e dividir a fatura são algoritmos simples — e dizemo-lo. |
| Dois aparelhos iguais em quartos diferentes? | Em produção cada quarto tem a sua tomada. Com um só medidor, cruzamos temperatura, presença e hábitos; se houver dúvida, perguntamos; sem resposta, divide-se por igual. |
| Porque é que um senhorio pagaria? | Deixa de absorver abusos (~53 €/mês por quarto abusivo), o kit paga-se em menos de 4 meses de inverno e acabam as discussões sobre a conta. |
| E a pessoa que gasta mais? | Escolheu a casa a saber as regras; ganha previsibilidade e plafond solidário. |
| E se a internet falhar? | Gateway 4G e visão local; sincroniza quando volta. |
| Já existe? | Apps como o Splitwise dividem valores mas não medem; submedição exige eletricista e não atribui por pessoa. Não conhecemos uma solução por quarto com IA para casas partilhadas em Portugal — confirmar antes do pitch. |
| O que ganha a Altice? | Receita recorrente por quarto, clientes MEO Energia e um caso de uso forte para a Connected Home. |

---

## 24 Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Câmara na porta percebida como vigilância | Imagem tapada a preto exceto a soleira; só contagens; votação; alternativa só com contacto + Wi-Fi. |
| Telemóveis a dormir ou com dados móveis | Tolerância de 20–30 min, confirmação pela porta, pergunta em caso de contradição. |
| Stream RTSP instável ou indisponível | Ensaiar a pipeline com um vídeo gravado; o pipeline é o mesmo. |
| Tomada lenta a atualizar no MCP | Aparelhos ligados ≥ 2 min; degraus bem distintos. |
| Wi-Fi da sala instável | Hotspot de telemóvel; vídeo de plano B gravado. |
| Consentimento inválido para a câmara | Segurança por interesse legítimo; zonas opcionais e sem custo para quem recusa. |
| Incentivo a passar frio | Plafond solidário + alertas privados de temperatura baixa. |
| O LLM inventar números | Só respostas de ferramentas; contas em código. |
| Ações perigosas | Tomadas protegidas; confirmação humana para segurança. |
| Senhorio querer controlar inquilinos | O painel só tem totais e alertas; não há forma técnica de ver presença ou imagens. |

---

## 25 Autoavaliação pelos critérios

*Avaliação com olhos de júri exigente (25% cada critério). É uma autoavaliação: serve para saber onde reforçar.*

| Critério | v1 | v2 | v3 | Porquê e o que falta |
|---|---:|---:|---:|---|
| **Enquadramento** | 16 | 17 | 18 | A câmara é a peça da presença (conta da sala, avisos); agente + MCP em todos os temas. Falta: mostrar a stream RTSP a funcionar. |
| **Facilidade de adoção** | 12 | 16 | 16 | Modelo do senhorio, câmara sem gravação, camadas. Falta: uma conversa real com um senhorio (→ 17). |
| **Viabilidade e sustentabilidade** | 13 | 15 | 16 | Medição realista (tomada por quarto + fatura), custos reais, plano de desenvolvimento detalhado. Falta: validar o preço. |
| **Apresentação do problema** | 15 | 16 | 16 | Quatro problemas reais e documentados. Falta: resultados do inquérito nos slides (→ 17–18). |
| **Geral** | 14 | 16 | 16,5 | Com inquérito, câmara provada e uma conversa com um senhorio: potencial realista de 17–18. |

*Versão 4: as três regras, o motor de presença, os orçamentos e os picos tornam o produto mais completo e real (viabilidade e adoção), mas aumentam o risco de execução em 2 dias — ver a secção 26.*

### 25.1 As três ações com maior impacto na nota

1. Lançar hoje o inquérito e pôr dois números no slide do problema.
2. Ter a stream RTSP a correr e mostrar o registo “o que sai da câmara”.
3. Falar com um senhorio e citar a resposta no pitch.

---

## 26 Pontos a repensar antes do pitch

*Uma leitura crítica de tudo o que foi decidido, para a equipa discutir.*

| # | Ponto | Porquê e o que propomos |
|---|---|---|
| 1 | **Câmara: só na porta** | Decidido: fogo e bolor saem do projeto; a câmara fica na porta como detetor de presença (como uma campainha inteligente, mas sem gravar). O sumário executivo foi atualizado em conformidade. |
| 2 | **A porta é o sítio mais sensível para uma câmara** | Vê todos os moradores e as visitas. Mesmo só a contar, o júri pode ver vigilância. Estejam prontos para responder com honestidade: o sensor de contacto + Wi-Fi já dão a maior parte do sinal; a câmara acrescenta o número de pessoas (incluindo visitas) e confirma saídas quando o Wi-Fi falha. Mostrem a imagem tapada a preto na demo. |
| 3 | **Não vender a presença como essencial** | A fatura base funciona só com as regras 1 e 2. A presença serve a opção C, os avisos e (fase 2) a segurança. Se o júri apertar, a resposta é “sem presença o sistema continua justo; com presença fica mais automático”. |
| 4 | **A opção C pode criar injustiças** | “Quem estava em casa” não é “quem usou”. Recomendamos a opção B (o bot pergunta) como padrão e a C só para casas que a escolham. |
| 5 | **Complexidade para 2 dias** | Assinaturas, presença, câmara, orçamento, picos, regras, bot… é muito. Mais vale quatro coisas a funcionar do que dez a meio. Protejam o núcleo da secção 19.1; as cenas de saída de casa ficam para a fase 2 (19.2). |
| 6 | **A latência do MCP pode estragar a demo** | Todo o motor de assinaturas depende da rapidez com que a tomada atualiza. É o primeiro teste da hora zero; se for lenta, os aparelhos ficam ligados mais tempo e o guião ajusta-se. |
| 7 | **Telemóveis e Wi-Fi** | Os telemóveis usam endereços aleatórios por rede (normalmente estáveis na mesma rede) e “dormem”. O registo tem de ser feito pelo bot, já ligado à rede da casa, e a fusão tem de tolerar falhas de 20–30 min. Testar no primeiro dia. |
| 8 | **Legal: dados e energia** | A ligação pessoa–quarto vem do contrato; a presença é opt-in; a câmara só conta. E o senhorio só pode repartir o custo real da fatura — vender eletricidade é uma atividade regulada. Validar com um jurista antes de qualquer piloto; no pitch, mostrar que pensaram nisto. |
| 9 | **Falta a validação do problema** | É a alavanca de nota mais barata: o inquérito e uma conversa com um senhorio. Sem isso, “os conflitos existem” continua a ser uma afirmação. |
| 10 | **Foco da história** | O coração é a casa justa: regras, assinaturas, presença e avisos. A segurança (casa vazia) é um bónus da fase 2 que vem da mesma câmara. |
| 11 | **Sem total da casa em tempo real** | Em produção só há as tomadas por quarto e a fatura mensal. Os mecanismos que comparam o “total” com as tomadas (localizar consumo em zona comum, camada 4 da secção 8) só existem no MVP, onde a tomada da extensão faz de medidor do total. Decidir como apresentar isto ao júri. |

---

## Fontes

- Kit e ferramentas: “Material recebido — Kit Connected Home · Altice Labs” e “Guia de ligação ao MCP Connected Home” (documentos da organização).
- Eurostat via Lusa (fev. 2026) — 14,5% sem capacidade de aquecer a casa em 2024: https://aman-alliance.org/Home/ContentDetail/99975
- DGES via HR Portugal — 447 680 estudantes em 2025/2026: https://hrportugal.sapo.pt/?p=468649
- Cobertura de residências de 8% e gestão de conflitos: https://ricavida.pt/quartos-para-estudantes-tudo-o-que-precisa-saber/
- Rendas de quartos (CM, ago. 2026): https://www.cmjornal.pt/sociedade/amp/mais-oferta-de-alojamento-nao-chega-para-baixar-rendas-dos-estudantes-deslocados
- E-REDES — 6,6 milhões de contadores inteligentes: https://rr.pt/noticia/economia/2024/12/06/substituicao-para-contadores-inteligentes-concluida-ao-fim-de-oito-anos/404822/
- ERSE — 99% das instalações BTN com contador inteligente: https://www.erse.pt/media/o0yaryjc/relat%C3%B3rio-redes-inteligentes-2025.pdf
- Registo de consumo em intervalos de 15 minutos: https://www.repsol.pt/particulares/assessoramento/contador-inteligente-eletricidade/
- MEO Energia — exclusiva para clientes MEO: https://selectra.pt/energia/empresas/meo-energia/opinioes
- MEO Energia — 50 mil clientes (Lusa/ECO, 2024): https://eco.sapo.pt/2024/05/27/meo-pretende-duplicar-clientes-de-energia-ate-final-do-ano/
- Horário de vazio: https://www.comparamais.pt/luz-e-gas/meo-energia
- Preços de dispositivos (4gnews): https://4gnews.pt/estes-gadgets-sao-o-segredo-para-teres-uma-casa-inteligente-barata/
- Mensalidade histórica MEO Smart Home (Pplware): https://pplware.sapo.pt/?p=490424
- Consentimento livre no RGPD (Comissão Europeia): https://commission.europa.eu/law/law-topic/data-protection/rules-business-and-organisations/legal-grounds-processing-data/grounds-processing/when-consent-valid_pt
- Bases legais (CEPD): https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_pt
- Câmaras em partes comuns (DECO Proteste): https://www.deco.proteste.pt/reclamar/todas-as-reclamacoes/cameras-de-video-vigilancia-/31a9e965bbbe62db68
- Aviso informativo na videovigilância (CGD): https://www.cgd.pt/Site/Saldo-Positivo/leis-e-impostos/Pages/leis-sistema-videovigilancia0621-2471.aspx
- Darby, S. (2006). *The effectiveness of feedback on energy consumption.* University of Oxford.

---

## Notas da versão 5.1

- **Modelos de IA (secção 9):** passam de seis para quatro componentes em três camadas (perceção, decisão, interface). A previsão, o orçamento e as anomalias fundiram-se com a presença no motor de decisão (M3), que é estatística e regras, não IA treinada. Corrigidas as referências cruzadas: a atribuição bayesiana é do M3 (antes aparecia como “M4”) e o exemplo completo é M2 + M3 + M4 no aquecedor do Bruno (6.5), não “M4 + M5 + M8 … a chaleira”.
- **Câmara:** a imagem chega pela stream RTSP.
- **Total da casa em tempo real:** removido (módulo HAN no contador e API Smart Metering Plus da E-REDES). Em produção medem-se as tomadas por quarto e a fatura; no MVP, a tomada da extensão faz de medidor do total.
- **Grupo do bot:** grupo de Telegram com os 4 moradores + o bot.
- **Saídas de casa:** aparelho esquecido e casa vazia/AWAY ficam para a fase 2 (19.2) e saem da demo e dos testes.
