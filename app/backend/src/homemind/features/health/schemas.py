from typing import Literal

from pydantic import BaseModel


class Health(BaseModel):
    status: Literal["ok"]
    mode: Literal["simulation", "real"]
    physical_writes: bool
