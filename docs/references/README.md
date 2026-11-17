# Referências

Documentos originais da proposta. **Não se editam**: são históricos.

| Ficheiro | O que é |
|---|---|
| [Conta_Certa_Documento_Completo.pdf](Conta_Certa_Documento_Completo.pdf) | Documento completo da Conta Certa (v5.0, 17/11/2026): ideia, plano de desenvolvimento, preparação da apresentação (39 páginas) |
| [Sumario_Executivo_Conta_Certa.pdf](Sumario_Executivo_Conta_Certa.pdf) | Sumário executivo (modelo da organização) |

## Onde divergem da documentação atual

Os PDFs descrevem **Telegram**, bot, grupo de mensagens, Streamlit e uma árvore de repositório própria (`collector/`, `vision/`…). **Essa parte foi substituída**: a aplicação React/Mantine/Capacitor é a interface única e o assistente vive nela. Ver [decisions.md](../decisions.md) (D-01 e mapeamento completo). Onde houver divergência, prevalece `docs/`.

Também **não** foram validados por nós os números de mercado, preços, payback e exemplos monetários do PDF (A-01 em [decisions.md](../decisions.md)).

## Guia oficial do MCP

`altice-mcp-guia-ligacao.pdf` (guia de ligação ao MCP da organização) esteve em `docs/`. Aparece apagado na árvore de trabalho antes desta reorganização e **não foi restaurado nem incluído no commit**. Ver P-09 em [decisions.md](../decisions.md).
