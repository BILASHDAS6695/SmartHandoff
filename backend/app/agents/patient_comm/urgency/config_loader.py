"""Configuration loader for urgency detection keywords and emergency contacts (US-044, TASK-001).

Loads and caches YAML configuration files at startup, converting them to
Pydantic-validated objects and compiled regex patterns.

Design refs:
    US-044 Technical Notes — configurable keyword list and emergency contacts
    design.md §7.3 AIR-021 — no PHI in configuration
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import yaml
from pydantic import ValidationError

from backend.app.agents.patient_comm.urgency.schemas import (
    EmergencyContactConfig,
    UrgencyKeywordConfig,
)

# Configuration file paths (relative to project root)
_KEYWORDS_YAML: Final[Path] = Path(__file__).parent.parent.parent.parent.parent / "config" / "urgency_keywords.yaml"
_EMERGENCY_YAML: Final[Path] = Path(__file__).parent.parent.parent.parent.parent / "config" / "emergency_contacts.yaml"

# Module-level caches — populated once on first load, then reused
_cached_patterns: list[re.Pattern[str]] | None = None
_cached_emergency_config: EmergencyContactConfig | None = None


def load_urgency_keywords() -> list[re.Pattern[str]]:
    """Load and compile urgency keywords from config/urgency_keywords.yaml.

    Returns:
        List of compiled regex patterns with word boundaries.
        Patterns are cached in module memory and reused across requests.

    Raises:
        FileNotFoundError: If config/urgency_keywords.yaml is missing
        ValidationError: If YAML does not match UrgencyKeywordConfig schema
        yaml.YAMLError: If YAML is malformed
    """
    global _cached_patterns

    if _cached_patterns is not None:
        return _cached_patterns

    if not _KEYWORDS_YAML.exists():
        raise FileNotFoundError(f"Urgency keywords config not found: {_KEYWORDS_YAML}")

    with open(_KEYWORDS_YAML, "r") as f:
        data = yaml.safe_load(f)

    # Validate against Pydantic schema
    config = UrgencyKeywordConfig(**data)

    # Compile regex patterns with word boundaries and case-insensitive flag
    patterns: list[re.Pattern[str]] = []
    for keyword in config.keywords:
        # Escape special regex characters and add word boundaries
        escaped = re.escape(keyword)
        pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
        patterns.append(pattern)

    _cached_patterns = patterns
    return patterns


def load_emergency_contact_config() -> EmergencyContactConfig:
    """Load emergency contact configuration from config/emergency_contacts.yaml.

    Returns:
        EmergencyContactConfig with primary_number, hospital_number, display_message, etc.
        Cached in module memory and reused across requests.

    Raises:
        FileNotFoundError: If config/emergency_contacts.yaml is missing
        ValidationError: If YAML does not match EmergencyContactConfig schema
        yaml.YAMLError: If YAML is malformed
    """
    global _cached_emergency_config

    if _cached_emergency_config is not None:
        return _cached_emergency_config

    if not _EMERGENCY_YAML.exists():
        raise FileNotFoundError(f"Emergency contacts config not found: {_EMERGENCY_YAML}")

    with open(_EMERGENCY_YAML, "r") as f:
        data = yaml.safe_load(f)

    # Extract the 'emergency' key and validate
    emergency_data = data.get("emergency", {})
    config = EmergencyContactConfig(**emergency_data)

    _cached_emergency_config = config
    return config
