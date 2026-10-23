"""The bot profile: what Telegram shows before a single message is sent.

These are behavioural tests over `vyron.core.botprofile.install()` with a fake
bot that records the calls, so the scopes (users / admins / owner) and the
"never leak a secret into the profile" rule are both enforced.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pyrogram")

from vyron.config import settings
from vyron.core import botprofile


class FakeBot:
    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[tuple[str, dict]] = []

    def _record(self, call: str, **kwargs) -> bool:
        if call in self.fail:
            raise RuntimeError(f"{call} is not available")
        self.calls.append((call, kwargs))
        return True

    async def set_bot_name(self, name):
        return self._record("set_bot_name", value=name)

    async def set_bot_info_short_description(self, text):
        return self._record("short", text=text)

    async def set_bot_info_description(self, text):
        return self._record("description", text=text)

    async def set_bot_commands(self, commands, scope=None, language_code=""):
        return self._record(
            "commands",
            commands=[command.command for command in commands],
            scope=type(scope).__name__ if scope else "default",
        )

    async def set_bot_default_privileges(self, privileges=None, for_channels=None):
        if "set_bot_default_privileges" in self.fail:
            raise RuntimeError("set_bot_default_privileges is not available")
        return self._record("privileges", privileges=privileges)

    def named(self, name: str) -> list[dict]:
        return [kwargs for call, kwargs in self.calls if call == name]


def test_install_sets_name_about_commands_and_rights():
    bot = FakeBot()
    report = asyncio.run(botprofile.install(bot))

    assert report == {"name": True, "about": True, "commands": True, "rights": True}
    assert bot.named("set_bot_name")[0]["value"] == "VYRON"
    assert "/play" in bot.named("description")[0]["text"]

    # the credentials never appear in anything Telegram shows publicly
    shown = " ".join(
        str(value)
        for _, kwargs in bot.calls
        for value in kwargs.values()
    )
    assert settings.bot_token not in shown
    assert "vown_" not in shown


def test_scoped_menus_hide_owner_tooling_from_users():
    bot = FakeBot()
    asyncio.run(botprofile.install(bot))

    scopes = {call["scope"]: call["commands"] for call in bot.named("commands")}
    assert "BotCommandScopeDefault" in scopes
    assert "BotCommandScopeAllChatAdministrators" in scopes

    every = set(scopes["BotCommandScopeDefault"])
    admins = set(scopes["BotCommandScopeAllChatAdministrators"])
    assert {"play", "song", "app", "help"} <= every
    assert "eval" not in every and "broadcast" not in every and "logs" not in every
    assert {"gadmin", "locks", "ban"} <= admins


def test_owner_scope_is_attempted_but_never_blocks_boot():
    """The owner may never have opened the bot — that must not raise."""

    class PickyBot(FakeBot):
        async def set_bot_commands(self, commands, scope=None, language_code=""):
            if type(scope).__name__ == "BotCommandScopeChat":
                raise RuntimeError("PEER_ID_INVALID")
            return await super().set_bot_commands(commands, scope=scope)

    bot = PickyBot()
    report = asyncio.run(botprofile.install(bot))
    assert report["commands"] is True


def test_a_missing_method_degrades_instead_of_crashing():
    bot = FakeBot(fail={"set_bot_name", "set_bot_default_privileges"})
    report = asyncio.run(botprofile.install(bot))
    assert report["name"] is False and report["rights"] is False
    assert report["about"] is True and report["commands"] is True


def test_profile_can_be_switched_off(monkeypatch):
    import dataclasses

    monkeypatch.setattr(
        botprofile, "settings", dataclasses.replace(settings, bot_profile=False)
    )
    bot = FakeBot()
    report = asyncio.run(botprofile.install(bot))
    assert not any(report.values()) and bot.calls == []
