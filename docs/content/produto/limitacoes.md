# Limitações conhecidas

## O que não está provado

- Tudo na demonstração é **SIMULADO**; nada foi validado com hardware real nesta fase.
- O assistente de IA só tem testes: não foi visto no browser, o LLM está desligado por omissão e os dados são simulados.
- Push e acesso offline não existem.
- A previsão mensal e o tarifário só têm testes; a opção C (presença) não está implementada.
- A verificação de email real para convites está bloqueada (#85).
- Prazos de retenção de presença e textos de privacidade são **PROPOSTA**, sem revisão jurídica nem política real de backups.
- Sem testes unitários de frontend; sem leitor de ecrã nem contraste medidos.

## Limites do hardware (observados em 17/11/2026, não reverificados)

| Limite | Impacto |
|---|---|
| Uma só tomada com medição | Sem quartos medidos; identificação só por assinatura |
| Unidade de `instantPower` não declarada (confirmada em W por medição) | Com `MCP_INSTANTPOWER_UNIT=W` há `measured`; sem ela, nunca |
| Escrita física na lâmpada e na tomada não comprovada | Feedback por cor e corte de tomada não podem ser REAL |
| Latência MCP de ~0,65–0,87 s por leitura | Degraus com resolução da ordem de segundos |
| Acesso à imagem da câmara do kit não provado para este uso | Contagem na porta incerta; plano B com clip ou presença manual |

## O que a Conta Certa não é

- **Não é vigilância:** sem reconhecimento facial, gravação, imagens ao senhorio nem venda de dados.
- **Não vende eletricidade:** o senhorio só reparte o custo real da fatura (validação jurídica por fazer).
- **Não é um contador certificado:** os valores são medições do kit ou estimativas, e cada recibo diz qual é qual.
- **Não é (ainda) um sistema de segurança:** armar alarmes reais e cenários do Connected Home estão fora do âmbito atual.

## Riscos

Riscos técnicos, legais e de produto estão em `docs/development/risks.md`, no repositório. Os riscos legais (câmara percebida como vigilância, RGPD, regulação da venda de eletricidade) vêm do documento de proposta e **não são aconselhamento jurídico**.

*Fontes canónicas: `docs/functional-flows.md`, `docs/development/risks.md`, `README.md`.*
