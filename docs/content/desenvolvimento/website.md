# Este website

Documentação publicada com **MkDocs + Material for MkDocs** em <https://souofrancisco.github.io/homemind/>.

## Onde está

| Caminho | Papel |
|---|---|
| `docs/content/` | Páginas publicadas. **Conteúdo público**: nunca segredos, dados pessoais ou informação operacional sensível |
| `docs/mkdocs.yml` | Configuração do site (`docs_dir: content`) |
| `docs/requirements.txt` | Dependências fixadas (`mkdocs`, `mkdocs-material`) |
| `docs/compose.yml`, `Dockerfile`, `serve.sh` | Pré-visualização local; o GitHub Pages não os usa |
| `.github/workflows/pr-docs.yml` | Valida em PR |
| `.github/workflows/publish-docs.yml` | Publica no GitHub Pages |

Os restantes ficheiros de `docs/` (evidência, arquivo, referências, planos) **não são publicados**.

## Correr localmente

Com Docker (a partir da raiz do repositório):

```bash
docker compose -f docs/compose.yml up docs
```

Abre em <http://localhost:8100> (a porta 8000 é a da API).

Sem Docker:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r docs/requirements.txt
mkdocs serve -f docs/mkdocs.yml
```

Com o `site_url` versionado, serve em <http://127.0.0.1:8000/homemind/>. Se a API local estiver a correr na 8000, acrescentar `--dev-addr 127.0.0.1:8100`.

## Validar

O mesmo comando que o CI corre:

```bash
mkdocs build -f docs/mkdocs.yml --strict
```

O HTML vai para `/tmp/homemind-docs-site`, fora do repositório. `--strict` falha em links, âncoras ou ficheiros de navegação em falta.

## Publicação automática

| Evento | Workflow | O que faz |
|---|---|---|
| Pull request para `main` | `pr-docs.yml` | `mkdocs build --strict`. Não publica |
| Push para `main` que altera `docs/content/**`, `docs/mkdocs.yml`, `docs/requirements.txt` ou `publish-docs.yml` | `publish-docs.yml` | Constrói o site e publica-o no ambiente `github-pages` |
| Execução manual (`workflow_dispatch`) | `publish-docs.yml` | O mesmo |

O repositório usa **GitHub Pages com origem «GitHub Actions»** (Settings → Pages → Build and deployment → Source). Deploys concorrentes não se sobrepõem.

!!! warning "O site é público"
    O GitHub Pages é público, mesmo que o repositório seja privado. Só entra em `docs/content/` o que pode ser lido por qualquer pessoa.

## Manter a documentação

- Cada página publicada resume um documento canónico em `docs/` e indica-o em «Fonte canónica». **Atualizar o documento canónico primeiro** e depois a página publicada, no mesmo PR.
- Distinguir sempre IMPLEMENTADO, PLANEADO e PROPOSTA. Não inventar estados nem resultados de testes.
- Ao acrescentar uma página, adicioná-la ao `nav` de `docs/mkdocs.yml`.
- Os workflows de documentação são independentes do workflow `CI` (desativado), que não se altera.
