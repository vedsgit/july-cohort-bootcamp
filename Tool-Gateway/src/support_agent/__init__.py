"""Governed tool gateway used by the LLM path and deterministic demos."""

from .factory import build_gateway
from .policy import POLICY_VERSION

__all__ = ["POLICY_VERSION", "build_gateway"]
