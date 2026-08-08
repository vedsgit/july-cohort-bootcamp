from __future__ import annotations


class ToolBoundaryError(Exception):
    """Deterministic execution failure with a stable reason code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
