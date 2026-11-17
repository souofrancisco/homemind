from pydantic import BaseModel, ConfigDict


class Contrato(BaseModel):
    """Base dos contratos partilhados: imutável e sem campos extra."""

    model_config = ConfigDict(frozen=True, extra="forbid")
