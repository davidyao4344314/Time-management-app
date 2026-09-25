"""Local, server-only configuration for a future OpenAI integration."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv, set_key


AI_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
