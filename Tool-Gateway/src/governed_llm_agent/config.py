from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _project_root() -> Path:
    # .../src/governed_llm_agent/config.py → project root (starter/ or instructor_solution/)
    return Path(__file__).resolve().parents[2]


def _find_env_file() -> Path | None:
    candidates = [
        Path.cwd() / ".env",
        _project_root() / ".env",
    ]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def _load_env() -> Path | None:
    """
    Load API keys and mode from .env.

    When a project .env exists, its values win (override=True) so demos use the
    keys maintained in that file even if the shell has a stale export.
    """
    env_path = _find_env_file()
    if env_path is not None:
        load_dotenv(env_path, override=True)
        return env_path
    load_dotenv(override=False)
    return None


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    mode: str  # "live" | "fake"
    env_file: str | None = None

    @property
    def is_live(self) -> bool:
        return self.mode == "live"


def load_settings() -> Settings:
    env_file = _load_env()

    raw_key = os.getenv("OPENAI_API_KEY")
    openai_api_key = raw_key.strip().strip('"').strip("'") if raw_key else None
    if openai_api_key == "" or openai_api_key.startswith("sk-your-key"):
        openai_api_key = None

    openai_model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

    mode = (os.getenv("GOVERNED_LLM_MODE") or "").strip().lower()
    if not mode:
        mode = "live" if openai_api_key else "fake"
    if mode not in {"live", "fake"}:
        raise ValueError("GOVERNED_LLM_MODE must be 'live' or 'fake'")

    if mode == "live" and not openai_api_key:
        location = env_file or (_project_root() / ".env")
        raise RuntimeError(
            "GOVERNED_LLM_MODE=live but OPENAI_API_KEY is missing. "
            f"Put your key in {location} (see .env.example)."
        )

    if openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key
    if openai_model:
        os.environ["OPENAI_MODEL"] = openai_model
    os.environ["GOVERNED_LLM_MODE"] = mode

    return Settings(
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        mode=mode,
        env_file=str(env_file) if env_file else None,
    )


def fake_settings() -> Settings:
    """Deterministic offline settings for unit tests (ignores .env mode)."""
    return Settings(
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        mode="fake",
        env_file=None,
    )
