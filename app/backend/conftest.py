"""Raiz dos testes do backend: nenhuma suite toca na base de dados local nem na rede."""

import os

# Antes de qualquer import da app: `homemind.main` chama get_settings() ao importar (CORS).
os.environ["DB_PATH"] = ":memory:"
