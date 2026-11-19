# Autenticação e autorização

## Autenticação

Login por **Authentik** (OIDC com PKCE). O backend valida o JWT; o `sub` do token liga-se a uma *membership* da casa, e dela vem o papel (`core/access.py`).

<span class="estado estado--ok">IMPLEMENTADO</span> Visto no browser com o Authentik local. A verificação de email real para convites está bloqueada (#85).

## Autorização por papel

Três papéis: morador (`tenant`), senhorio (`landlord`) e operador (`operator`). A autorização é feita **no servidor**, com DTOs de resposta distintos por papel; cada rota nova tem um teste papel × rota.

Verificado por HTTP com o token de cada conta: sem token → 401; o senhorio recebe 403 em recibos pessoais, presença e aparelhos; o morador recebe 403 em faturas do senhorio. Ver [isolamento por papel](../demo/verificado.md#isolamento-por-papel).

## Privacidade (regras inegociáveis)

- **Vídeo só local:** nunca se grava, regista nem envia frames; só a soleira da porta é analisada; sem reconhecimento facial. Saem apenas eventos («entrou» / «saiu») e visitas como número.
- A identidade de presença vem do telemóvel registado (opt-in), nunca da imagem.
- **RBAC:** o senhorio vê totais mensais por quarto e alertas; **nunca** presença, horários, curvas horárias ou imagens.
- **Consentimento por fonte** (Wi-Fi, aparelho a ligar, resposta manual): tudo desligado por omissão; desligar uma fonte apaga só os dados dela.
- **Segredos** (chaves, tokens, URL RTSP) só em ficheiros locais fora do Git; nunca em logs, erros, testes ou documentação.

O inventário de dados pessoais está em `docs/privacy/inventario-dados-pessoais.md`. É uma **PROPOSTA**: não afirma conformidade legal.

*Fontes canónicas: `CLAUDE.md` (Parte C), `docs/product/personas.md`.*
