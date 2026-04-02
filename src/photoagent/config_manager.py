"""Configuration management for PhotoAgent.

Handles API key storage (keyring + env fallback) and persistent
user preferences in ~/.photoagent/config.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_CONFIG_DIR = Path.home() / ".photoagent"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# Valid configuration keys
_VALID_KEYS = {
    "default_extensions",
    "preferred_device",
    "default_template",
}


class ConfigManager:
    """Manage API keys and user configuration."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # API key management
    # ------------------------------------------------------------------

    def get_api_key(self) -> str | None:
        """Retrieve the Anthropic API key.

        Checks keyring first, then the ANTHROPIC_API_KEY env var.

        Returns
        -------
        The API key string, or None if not found.
        """
        # 1. Try keyring
        try:
            import keyring

            stored = keyring.get_password("photoagent", "anthropic_api_key")
            if stored:
                return stored
        except Exception:
            pass

        # 2. Try environment variable
        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key:
            return env_key

        return None

    def set_api_key(self, key: str) -> None:
        """Store the Anthropic API key in the system keyring.

        Parameters
        ----------
        key:
            The API key string to store.
        """
        import keyring

        keyring.set_password("photoagent", "anthropic_api_key", key)

    # ------------------------------------------------------------------
    # Config file management
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """Read the configuration from ~/.photoagent/config.json.

        Returns
        -------
        Configuration dict. Returns empty dict if the file does not exist.
        """
        if not _CONFIG_FILE.exists():
            return {}

        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass

        return {}

    def set_config(self, **settings: Any) -> None:
        """Write configuration settings to ~/.photoagent/config.json.

        Merges the provided settings with existing configuration.
        Only accepts known configuration keys.

        Parameters
        ----------
        **settings:
            Key-value pairs to store. Supported keys:
            default_extensions, preferred_device, default_template.
        """
        # Validate keys
        unknown = set(settings.keys()) - _VALID_KEYS
        if unknown:
            raise ValueError(
                f"Unknown config keys: {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(_VALID_KEYS))}"
            )

        # Read existing config
        config = self.get_config()

        # Merge new settings
        config.update(settings)

        # Write back
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
