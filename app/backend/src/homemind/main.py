from fastapi import FastAPI

from homemind.core.features import register_features

app = FastAPI(title="HomeMind Spaces API")
register_features(app)
