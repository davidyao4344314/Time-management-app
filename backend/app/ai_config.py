"""Local, server-only configuration for OpenAI requests."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv, set_key


AI_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
AGENT_MODEL_OPTIONS = {
    "gpt-6-luna": ("none", "low", "medium", "high", "xhigh", "max"),
    "gpt-6-sol": ("none", "low", "medium", "high", "xhigh", "max"),
    "gpt-6.1-sol": ("low", "medium", "high", "xhigh", "max"),
    "gpt-6-astra": ("low", "medium", "high", "xhigh", "max"),
}
DEFAULT_AGENT_MODEL = "gpt-6-luna"
DEFAULT_AGENT_REASONING_EFFORT = "none"


def get_agent_model_settings():
    """Return non-secret settings for the main study agent only."""
    load_dotenv(AI_ENV_FILE)
    model = os.getenv("OPENAI_AGENT_MODEL", DEFAULT_AGENT_MODEL)
    effort = os.getenv("OPENAI_AGENT_REASONING_EFFORT", DEFAULT_AGENT_REASONING_EFFORT)
    if model not in AGENT_MODEL_OPTIONS:
        model = DEFAULT_AGENT_MODEL
    if effort not in AGENT_MODEL_OPTIONS[model]:
        effort = "low" if model != DEFAULT_AGENT_MODEL else DEFAULT_AGENT_REASONING_EFFORT
    return {"model": model, "reasoning_effort": effort}


def save_agent_model_settings(model, reasoning_effort):
    """Persist an approved OpenAI model/effort pair in the ignored local .env."""
    if not isinstance(model, str) or model not in AGENT_MODEL_OPTIONS:
        raise ValueError("Choose a supported OpenAI model.")
    if not isinstance(reasoning_effort, str) or reasoning_effort not in AGENT_MODEL_OPTIONS[model]:
        raise ValueError("Choose a reasoning effort supported by that model.")

    try:
        if AI_ENV_FILE.is_symlink():
            raise RuntimeError("The local configuration file cannot be a symlink.")
        if not AI_ENV_FILE.exists():
            descriptor = os.open(AI_ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        AI_ENV_FILE.chmod(0o600)
        for key, value in (
            ("OPENAI_AGENT_MODEL", model),
            ("OPENAI_AGENT_REASONING_EFFORT", reasoning_effort),
        ):
            saved, _, _ = set_key(AI_ENV_FILE, key, value)
            if not saved:
                raise RuntimeError("Could not save the local model settings.")
        AI_ENV_FILE.chmod(0o600)
    except OSError:
        raise RuntimeError("Could not save the local model settings.") from None

    os.environ["OPENAI_AGENT_MODEL"] = model
    os.environ["OPENAI_AGENT_REASONING_EFFORT"] = reasoning_effort
    return {"model": model, "reasoning_effort": reasoning_effort}


def is_openai_api_key_configured():
    """Report presence only; never return the key itself."""
    load_dotenv(AI_ENV_FILE)
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def save_openai_api_key(value):
    """Save a key in the ignored project .env and update this process."""
    key = value.strip() if isinstance(value, str) else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,512}", key):
        raise ValueError("Enter a valid API key without spaces.")

    try:
        if AI_ENV_FILE.is_symlink():
            raise RuntimeError("The local configuration file cannot be a symlink.")
        if not AI_ENV_FILE.exists():
            descriptor = os.open(
                AI_ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            os.close(descriptor)

        # Restrict the existing file before writing and the replacement after.
        AI_ENV_FILE.chmod(0o600)
        saved, _, _ = set_key(AI_ENV_FILE, "OPENAI_API_KEY", key)
        if not saved:
            raise RuntimeError("Could not save the local API key.")
        AI_ENV_FILE.chmod(0o600)
    except OSError:
        raise RuntimeError("Could not save the local API key.") from None

    os.environ["OPENAI_API_KEY"] = key
