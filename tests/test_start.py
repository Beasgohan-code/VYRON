"""`/start` — the private onboarding card and the group setup card.

A private `/start` answers "what is this bot". A group `/start` has to answer
"is it set up *here*, and what is still missing", so it reads the bot's real
rights in that chat instead of repeating the manual. These tests pin both.
"""
from __future__ import annotations

from types import SimpleNamespace

from vyron.ui import cards, rich


def _privileges(**overrides):
    base = {
        "can_manage_video_chats": True,
        "can_delete_messages": True,
        "can_invite_users": True,
        "can_pin_messages": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_an_owner_has_every_right_the_bot_needs():
    from vyron.modules.start import _rights_from_member

    rights = _rights_from_member(SimpleNamespace(status="ChatMemberStatus.OWNER", privileges=None))

    assert rights == {"voice": True, "delete": True, "invite": True, "pin": True}


def test_an_admin_is_judged_by_its_privilege_object():
    from vyron.modules.start import _rights_from_member

    rights = _rights_from_member(
        SimpleNamespace(
            status=SimpleNamespace(name="ADMINISTRATOR"),
            privileges=_privileges(can_delete_messages=False, can_pin_messages=False),
        )
    )

    assert rights["voice"] is True and rights["invite"] is True
    assert rights["delete"] is False and rights["pin"] is False


def test_a_plain_member_has_no_rights_at_all():
    from vyron.modules.start import _rights_from_member

    rights = _rights_from_member(
        SimpleNamespace(status="ChatMemberStatus.MEMBER", privileges=_privileges())
    )

    assert not any(rights.values())


def test_the_group_card_names_the_chat_and_who_added_the_bot():
    text = rich.to_plain_text(
        cards.group_start_card(
            "Lofi Lounge",
            ("Rahul", 42),
            {"voice": True, "delete": False, "invite": True, "pin": False},
            {"chats": 12, "tracks": 340},
        )
    )

    assert "Lofi Lounge" in text and "Rahul" in text
    assert "manage voice chats" in text and "delete messages" in text
    # The missing ones are named, so an admin knows exactly what to tick.
    assert "still to grant" in text
    assert "delete messages" in text.split("still to grant", 1)[0]


def test_the_group_card_says_when_nothing_is_missing():
    text = rich.to_plain_text(
        cards.group_start_card(
            "Lofi Lounge",
            "there",
            {"voice": True, "delete": True, "invite": True, "pin": True},
            {},
        )
    )

    assert "Nothing else to set up" in text
    assert "still to grant" not in text


def test_an_unreadable_permission_probe_is_not_reported_as_a_failure():
    text = rich.to_plain_text(cards.group_start_card("Room", "there", None, {}))
    assert "could not read my own permissions" in text
    assert "missing" not in text


def test_the_group_card_keeps_at_most_four_buttons():
    markup = cards.group_start_card("Room", "there", {"voice": True}, {})
    assert markup.count("<tg-button ") <= 4


def test_a_group_that_is_already_playing_gets_the_track_not_the_manual():
    text = rich.to_plain_text(
        cards.group_start_card(
            "Room",
            "there",
            {"voice": True},
            {},
            live={"title": "Kesariya", "queue": 2, "paused": False},
        )
    )

    assert "Kesariya" in text and "already playing here" in text
    assert "what i need here" not in text
