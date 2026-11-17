import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from homemind.core.config import get_settings
from homemind.core.errors import register_errors
from homemind.core.features import register_features
from homemind.core.lifespan import core_lifespan

# O uvicorn só configura os seus próprios loggers: sem isto os INFO da app (visão ligada,
# tempos das escritas MCP) perdiam-se. Nunca se registam segredos, URLs de vídeo nem frames.
_log = logging.getLogger("homemind")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)

# O lifespan do core é o da app: arranca antes e termina depois dos lifespans dos routers.
app = FastAPI(title="ObjectOS API", lifespan=core_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
register_errors(app)
register_features(app)
