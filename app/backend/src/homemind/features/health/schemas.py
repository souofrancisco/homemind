from typing import Literal

from pydantic import BaseModel


class Health(BaseModel):
    status: Literal["ok"]
    backend: Literal["fake", "mcp"]  # fake = SIMULADO (FakeHome)
    physical_writes: bool
