"""Future response-planning interface only; no model calls or planning loops."""

from typing import Protocol

from pydantic import JsonValue


class ResponsePlanner(Protocol):
    def plan(self, request: str) -> dict[str, JsonValue]:
        """Eventually plan a complex response, not approve or execute app changes."""
        ...
