"""Escreve o OpenAPI da app em stdout (contrato para o frontend): `python -m homemind.openapi`."""

import json

from homemind.main import app

print(json.dumps(app.openapi(), indent=2, sort_keys=True))
