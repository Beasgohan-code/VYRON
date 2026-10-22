"""Startup validation: what blocks boot, what only downgrades a feature."""
from __future__ import annotations

import dataclasses

from vyron.config import Settings


def _settings(**overrides) -> Settings:
    base = Settings()
    kwargs = {
        "bot_token": "123456789:TEST-TOKEN",
        "api_id": 123456,
        "api_hash": "0123456789abcdef0123456789abcdef",
        "session_string": "",
        "owner_id": 424242,
        "sudo_users": (),
        "webapp": False,
        "webapp_url": "",
    }
    kwargs.update(overrides)
    return dataclasses.replace(base, **kwargs)


def test_complete_config_has_no_errors_and_no_warnings():
    cfg = _settings(session_string="SESSION-STRING")
    assert cfg.validate() == []
    assert cfg.warnings() == []


def test_missing_session_is_only_a_warning():
    cfg = _settings()
    assert cfg.validate() == []                       # boots in file-only mode
    notes = " ".join(cfg.warnings())
    assert "STRING_SESSION" in notes
    assert "file" in notes


def test_missing_owner_is_only_a_warning():
    cfg = _settings(session_string="x", owner_id=0, sudo_users=())
    assert cfg.validate() == []
    assert "OWNER_ID" in " ".join(cfg.warnings())


def test_sudo_users_satisfy_the_owner_warning():
    cfg = _settings(session_string="x", owner_id=0, sudo_users=(99,))
    assert cfg.warnings() == []


def test_credentials_still_block_boot():
    cfg = _settings(bot_token="", api_id=0, api_hash="", session_string="x")
    errors = cfg.validate()
    assert any("BOT_TOKEN" in item for item in errors)
    assert any("API_ID" in item for item in errors)
    assert any("API_HASH" in item for item in errors)
    # nothing about the optional pieces
    assert not any("STRING_SESSION" in item for item in errors)


def test_webapp_without_url_warns():
    cfg = _settings(session_string="x", webapp=True, webapp_url="")
    assert "WEBAPP_URL" in " ".join(cfg.warnings())
    assert not cfg.webapp_ready

    cfg = _settings(session_string="x", webapp=True, webapp_url="https://vyron.example")
    assert cfg.webapp_ready and cfg.warnings() == []
