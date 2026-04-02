"""Tests for photoagent.config_manager — ConfigManager API key + config management.

These tests validate setting/getting config values, persistence across
instances, default values, and API key resolution from environment.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Lazy import
# ------------------------------------------------------------------

def _get_config_manager():
    try:
        from photoagent.config_manager import ConfigManager
        return ConfigManager
    except ImportError:
        pytest.skip("photoagent.config_manager not yet implemented")


# ==================================================================
# Tests
# ==================================================================

class TestConfigManager:
    """Verify config storage, retrieval, persistence, and API key resolution."""

    def test_set_and_get_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import photoagent.config_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cm_mod, "_CONFIG_FILE", tmp_path / "config.json")

        ConfigManager = _get_config_manager()
        cm = ConfigManager()

        cm.set_config(default_extensions=".jpg,.png", preferred_device="cpu", default_template="by-date")

        config = cm.get_config()
        assert config["default_extensions"] == ".jpg,.png"
        assert config["preferred_device"] == "cpu"
        assert config["default_template"] == "by-date"

    def test_config_default_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import photoagent.config_manager as cm_mod
        fresh_path = tmp_path / "fresh_config"
        fresh_path.mkdir()
        monkeypatch.setattr(cm_mod, "_CONFIG_DIR", fresh_path)
        monkeypatch.setattr(cm_mod, "_CONFIG_FILE", fresh_path / "config.json")

        ConfigManager = _get_config_manager()
        cm = ConfigManager()

        # Getting config with no prior file should return empty dict or defaults
        config = cm.get_config()
        assert isinstance(config, dict)

    def test_config_persists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import photoagent.config_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cm_mod, "_CONFIG_FILE", tmp_path / "config.json")

        ConfigManager = _get_config_manager()

        # Set values with first instance
        cm1 = ConfigManager()
        cm1.set_config(preferred_device="gpu", default_template="by-camera")

        # Create a new instance pointing to same directory
        cm2 = ConfigManager()
        config = cm2.get_config()
        assert config["preferred_device"] == "gpu"
        assert config["default_template"] == "by-camera"

    def test_api_key_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import photoagent.config_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cm_mod, "_CONFIG_FILE", tmp_path / "config.json")

        ConfigManager = _get_config_manager()
        cm = ConfigManager()

        test_key = "sk-ant-test-key-12345"
        monkeypatch.setenv("ANTHROPIC_API_KEY", test_key)

        api_key = cm.get_api_key()
        assert api_key == test_key

    def test_api_key_not_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import photoagent.config_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cm_mod, "_CONFIG_FILE", tmp_path / "config.json")

        ConfigManager = _get_config_manager()
        cm = ConfigManager()

        # Ensure the env var is not set
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        api_key = cm.get_api_key()
        assert api_key is None or api_key == ""

    def test_set_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import photoagent.config_manager as cm_mod
        monkeypatch.setattr(cm_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cm_mod, "_CONFIG_FILE", tmp_path / "config.json")

        ConfigManager = _get_config_manager()
        cm = ConfigManager()

        cm.set_config(default_template="by-date")
        assert cm.get_config()["default_template"] == "by-date"

        cm.set_config(default_template="by-camera")
        assert cm.get_config()["default_template"] == "by-camera"
