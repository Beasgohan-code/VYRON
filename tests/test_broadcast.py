# ---------------------------------------------------------------------------
#  /broadcast — the flags, and what each one posts.
# ---------------------------------------------------------------------------
from __future__ import annotations

from vyron.modules.admin import _parse_flags, _strip_flags


def test_pin_flag_does_not_swallow_pinloud():
    assert _parse_flags("-pin") == (True, False, False, False)
    assert _parse_flags("-pinloud") == (False, True, False, False)


def test_every_flag_is_independent():
    assert _parse_flags("-nogroup -user") == (False, False, True, True)
    assert _parse_flags("no flags here") == (False, False, False, False)


def test_flags_are_stripped_from_the_message():
    assert _strip_flags("-pin hello world") == "hello world"
    assert _strip_flags("-pinloud -user hi there") == "hi there"
    assert _strip_flags("-pinloud") == ""
