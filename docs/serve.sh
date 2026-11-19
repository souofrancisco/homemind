#!/bin/sh
# Serve o site na raiz da porta 8000 do contentor.
# O mkdocs.yml versionado mantém o site_url do GitHub Pages (/homemind/), que
# faria o servidor de desenvolvimento montar o site nesse subcaminho.
set -eu
cd /docs
# A configuração gerada fica ao lado do mkdocs.yml para docs_dir: content continuar a resolver.
awk '
  /^site_url:/ { print "site_url: http://127.0.0.1:8000/"; next }
  { print }
' mkdocs.yml > /docs/mkdocs.serve.yml
exec mkdocs serve -f /docs/mkdocs.serve.yml --dev-addr 0.0.0.0:8000
