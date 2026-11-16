from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from homemind.core.config import get_settings
from homemind.core.errors import register_errors
from homemind.core.features import register_features

app = FastAPI(title="HomeMind Spaces API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
register_errors(app)
register_features(app)
