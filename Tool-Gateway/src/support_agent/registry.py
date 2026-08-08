from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel

from .contracts import Operation, RiskTier


ToolHandler = Callable[[BaseModel, str | None], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    operation: Operation
    risk_tier: RiskTier
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    allowed_roles: frozenset[str]
    requires_approval: bool = False
    approval_roles: frozenset[str] = frozenset()
    amount_limit: Decimal | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools[name] for name in self.names())

    def json_schemas(self) -> dict[str, dict[str, Any]]:
        """Export JSON Schema for each registered tool boundary."""
        return {
            tool.name: {
                "input": tool.input_model.model_json_schema(),
                "output": tool.output_model.model_json_schema(),
                "operation": tool.operation.value,
                "risk_tier": tool.risk_tier.value,
                "requires_approval": tool.requires_approval,
            }
            for tool in self.definitions()
        }
