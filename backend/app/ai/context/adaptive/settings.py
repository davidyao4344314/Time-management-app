"""Small opt-in controls. No configuration writes or model calls."""

import os
from dataclasses import dataclass

SCHEMA_VERSION = 1
ROUTER_VERSION = "adaptive-v1"
MIN_CONFIRMED_SAMPLES = 30
PROMOTION_AGREEMENT = 0.97
DEMOTION_AGREEMENT = 0.90
MIN_EVIDENCE_DAYS = 3
EVIDENCE_WINDOW = 100
EVIDENCE_MAX_DAYS = 90
STALE_AFTER_DAYS = 30
MAX_EXAMPLES = 3
MAX_EXAMPLE_CHARS = 600
MAX_EXAMPLES_CHARS = 1800
MIN_CALIBRATION_SAMPLES = 50
MIN_HIGH_CONFIDENCE_AGREEMENT = 0.95
AUDIT_EVERY = 20
AUDIT_DAILY_LIMIT = 5


@dataclass(frozen=True)
class AdaptiveSettings:
    mode: str = "off"
    examples_enabled: bool = False
    calibration_enabled: bool = False
    audits_enabled: bool = False

    def __post_init__(self):
        if self.mode not in {"off", "observe", "shadow", "active"}:
            raise ValueError("Invalid adaptive routing mode.")


def get_adaptive_settings():
    """Invalid local settings disable adaptation instead of breaking routing."""
    mode = os.getenv("AI_ADAPTIVE_ROUTING_MODE", "off").strip().lower()
    enabled = lambda name: os.getenv(name, "").strip().lower() in {"1", "true"}
    try:
        return AdaptiveSettings(
            mode=mode,
            examples_enabled=enabled("AI_ADAPTIVE_STAGE2_EXAMPLES"),
            calibration_enabled=enabled("AI_ADAPTIVE_CALIBRATION"),
            audits_enabled=enabled("AI_ADAPTIVE_AUDITS"),
        )
    except ValueError:
        return AdaptiveSettings()
