"""Redact conversation API keys without importing memory or agent services."""

import os
import re


_API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{16,}")


def redact_secrets(value):
    """Avoid persisting an API key if one was pasted into a conversation."""
    if isinstance(value, str):
        value = _API_KEY_PATTERN.sub("[redacted API key]", value)
        configured_key = os.getenv("OPENAI_API_KEY", "").strip()
        if len(configured_key) >= 16:
            value = value.replace(configured_key, "[redacted API key]")
        return value
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_secrets(item) for key, item in value.items()}
    return value
