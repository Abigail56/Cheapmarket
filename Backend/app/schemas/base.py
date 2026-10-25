from pydantic import ConfigDict
from sqlmodel import SQLModel


class ReadModel(SQLModel):
    """Mix into response schemas built on a model's `*Base`. The API always returns
    every field, so mark defaulted fields as required in the OpenAPI output too
    (otherwise generated frontend types make them optional)."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
