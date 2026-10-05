"""Safe public errors; exception details and request bodies are never returned."""
from typing import Literal
from pydantic import Field
from .contracts import PublicModel


class ErrorResponse(PublicModel):
    error: Literal["invalid_request", "unavailable", "not_found", "unauthorized", "forbidden"]
    message: str = Field(max_length=256)
