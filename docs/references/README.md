# Referências

Documentos originais da proposta. **Não se editam**: são históricos.

| Ficheiro | O que é |
|---|---|
| [Conta_Certa_Documento_Completo.pdf](Conta_Certa_Documento_Completo.pdf) | Documento completo da Conta Certa (v5.0, 17/11/2026): ideia, plano de desenvolvimento, preparação da apresentação (39 páginas) |
| [Conta_Certa_Documento_Completo_v5.1.md](Conta_Certa_Documento_Completo_v5.1.md) | **Versão 5.1** (17/11/2026), cópia integral e inalterada do texto fornecido pela equipa. É a fonte de produto referida como «v5.1» (§n). Sucede ao PDF v5.0 |
| [altice-mcp-guia-ligacao.pdf](altice-mcp-guia-ligacao.pdf) | Guia oficial de ligação ao MCP Connected Home (Altice Labs). Movido de `docs/` (histórico Git preservado) |
| [Sumario_Executivo_Conta_Certa.pdf](Sumario_Executivo_Conta_Certa.pdf) | Sumário executivo (modelo da organização) |

## Onde divergem da documentação atual

Os PDFs descrevem **Telegram**, bot, grupo de mensagens, Streamlit e uma árvore de repositório própria (`collector/`, `vision/`…). **Essa parte foi substituída**: a aplicação React/Mantine/Capacitor é a interface única e o assistente vive nela. Ver [decisions.md](../decisions.md) (D-01 e mapeamento completo). Onde houver divergência, prevalece `docs/`.

Também **não** foram validados por nós os números de mercado, preços, payback e exemplos monetários do PDF (A-01 em [decisions.md](../decisions.md)).

## v5.1 vs. decisões da equipa

A v5.1 mantém Telegram, grupo de mensagens e Streamlit nos §3, §6.9, §12, §16–17 e §19. Essas partes estão **substituídas** pela decisão D-01 (aplicação). Mantém também a segurança AWAY e os aparelhos esquecidos na fase 2 (§19.2), o que coincide com a documentação atual. Não editar o ficheiro; registar divergências em [decisions.md](../decisions.md).
