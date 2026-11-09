"""Build the chat model from .env settings.

Settings:
    OPENAI_API_KEY          required
    MODEL_NAME              required, a tool capable model
    OPENAI_BASE_URL         optional, for an OpenAI compatible provider
    MODEL_TEMPERATURE       optional, empty means do not send
    MODEL_REASONING_EFFORT  optional, empty means do not send
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

from helpdesk.data import REPO_ROOT


def load_env() -> None:
    """Read .env from the repository root without overriding real environment variables."""
    load_dotenv(REPO_ROOT / ".env")
    os.environ.setdefault("LANGSMITH_TRACING", "false")


def model_info() -> dict:
    """Model name and provider for logs. Never includes the key."""
    load_env()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    provider = urlparse(base_url).hostname if base_url else "api.openai.com"
    return {
        "name": os.environ.get("MODEL_NAME", "").strip() or None,
        "provider": provider,
        "temperature": os.environ.get("MODEL_TEMPERATURE", "").strip() or None,
        "reasoning_effort": os.environ.get("MODEL_REASONING_EFFORT", "").strip() or None,
    }


def make_model():
    """Return a ChatOpenAI model configured from .env."""
    load_env()
    from langchain_openai import ChatOpenAI  # imported here so Part 1 never needs it

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model_name = os.environ.get("MODEL_NAME", "").strip()
    missing = [name for name, value in (("OPENAI_API_KEY", api_key), ("MODEL_NAME", model_name)) if not value]
    if missing:
        raise RuntimeError(
            f"Missing {', '.join(missing)}. Copy .env.example to .env and fill them in "
            "(Part 1 and the tests do not need them)."
        )

    kwargs = {
        "model": model_name,
        "api_key": api_key,
        "base_url": os.environ.get("OPENAI_BASE_URL", "").strip() or None,
    }
    temperature = os.environ.get("MODEL_TEMPERATURE", "").strip()
    if temperature:
        kwargs["temperature"] = float(temperature)
    effort = os.environ.get("MODEL_REASONING_EFFORT", "").strip()
    if effort:
        kwargs["reasoning_effort"] = effort
    return ChatOpenAI(**kwargs)
