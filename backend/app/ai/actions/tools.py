"""Trusted tool contract. Handlers are optional; public contracts omit them."""

import re
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, JsonValue, ValidationError

from backend.app.ai.actions.contracts import ActionLayerError


class InvalidToolArgumentsError(ActionLayerError):
    pass


class ToolExecutionUnavailableError(ActionLayerError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: Callable[[dict[str, JsonValue]], dict[str, JsonValue]] | None = field(
        default=None, repr=False,
    )

    def __post_init__(self):
        if not isinstance(self.name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise ValueError("Tool names must be lowercase identifiers.")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("A tool description is required.")
        if not isinstance(self.arguments_model, type) or not issubclass(self.arguments_model, BaseModel):
            raise ValueError("Tools require a validated input model.")
        if self.handler is not None and not callable(self.handler):
            raise ValueError("A tool handler must be callable.")

    def public_contract(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.arguments_model.model_json_schema(),
        }

    def validate(self, arguments):
        try:
            return self.arguments_model.model_validate(arguments, strict=True).model_dump(mode="json")
        except ValidationError:
            # Validation details can echo user input. Keep the boundary error safe.
            raise InvalidToolArgumentsError("The tool arguments are invalid.") from None

    def execute(self, arguments):
        if self.handler is None:
            raise ToolExecutionUnavailableError("Execution is not available for this tool.")
        return self.handler(self.validate(arguments))
