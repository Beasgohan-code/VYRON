# ---------------------------------------------------------------------------
#  VYRON — how a track's name is written for a person
# ---------------------------------------------------------------------------
#  A play bot shows a name in three places — the now-playing card, the poster
#  drawn from it, and the file it sends — and all three used to repeat whatever
#  the uploader called it. That is how a card ended up reading
#
#      Alone_BoYtm - Chris Grey – LET THE WORLD BURN
#
#  for a song whose actual name is "LET THE WORLD BURN" by Chris Grey: the
#  uploader is a repost account, and the artist was already in the title. One
#  rule set, applied everywhere, keeps the name a person would write.
from __future__ import annotations

import re
from typing import Any

#: The separators people use between artist and title. Ordered longest first so
#: " – " wins over " - " and the split lands on the real one.
DASHES = (" – ", " — ", " - ", " ~ ", " • ")

#: Bracketed credits that add nothing to a name you read at a glance.
_NOISE = re.compile(
    r"\s*[\(\[]\s*(?:"
    r"official\s*(?:music\s*)?(?:video|audio|lyric\s*video|visualizer)"
    r"|lyrics?(?:\s*video)?|audio|full\s*song|hd|4k|8k|explicit"
    r")\s*[\)\]]",
    re.I,
)

#: Handles that are a channel, not an artist. A repost account is not part of
#: the song's name, and printing it made the bot look like it did not know what
#: it was playing.
_NOT_AN_ARTIST = re.compile(r"(?i)\b(topic|vevo|records|official|music|channel|uploads?)\b")


def clean_name(text: Any, *, limit: int = 120) -> str:
    """Trim a title without changing what it says."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value[:limit].strip()


def looks_like_artist(text: Any) -> bool:
    """Is *text* plausibly a person or band, rather than a channel handle?"""
    value = clean_name(text)
    if not value or len(value) > 42:
        return False
    if value.lower().endswith("- topic"):
        return False
    return not bool(_NOT_AN_ARTIST.search(value))


def display_parts(
    title: Any, uploader: Any = "", *, strip_credits: bool = True
) -> tuple[str, str]:
    """``(artist, name)`` for a track, the way a person would write it.

    * the artist already inside the title wins — "Chris Grey – LET THE WORLD
      BURN" is the artist's own naming and needs no help from a repost account;
    * otherwise the uploader is the artist, unless it is plainly a channel;
    * bracketed credits ("(Official Video)", "[4K]") are dropped for display.
    """
    name = clean_name(title)
    if strip_credits:
        name = clean_name(_NOISE.sub("", name)) or name

    for dash in DASHES:
        if dash in name:
            left, _, right = name.partition(dash)
            left, right = left.strip(), right.strip()
            if left and right:
                artist = left[:_NOT_ARTIST_LIMIT] if len(left) > _NOT_ARTIST_LIMIT else left
                return clean_name(artist, limit=60), clean_name(right)
            break

    artist = clean_name(uploader)
    # "Artist - Topic" is YouTube's own auto-generated label channel for a
    # label's audio: the most reliable "this is the artist" signal there is,
    # once the suffix is off.
    topic = re.match(r"(?i)^(.+?)\s*-\s*topic$", artist)
    if topic:
        artist = topic.group(1).strip()
    elif artist and not looks_like_artist(artist):
        artist = ""
    return clean_name(artist, limit=60), name


#: A "prefix" longer than this is a sentence, not an artist name.
_NOT_ARTIST_LIMIT = 44


#: Greek capitals that are just Latin letters wearing a toga — how stylised
#: display names ("𝚩𝚵𝚲𝐒𝚻") come back after NFKC normalisation.
_HOMOGLYPHS = str.maketrans(
    {
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
        "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
        "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
        "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "Σ": "S", "Λ": "A", "Ξ": "E",
        "Π": "P", "Θ": "O", "Δ": "A", "Φ": "F", "Ψ": "Y", "Ω": "O",
        # Cyrillic, for the same reason
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
        "О": "O", "Р": "P", "Т": "T", "У": "Y", "Х": "X", "а": "a", "е": "e",
        "о": "o", "р": "p", "с": "c", "у": "y", "х": "x",
        # and the decorative circles people use for an "O"
        "❍": "O", "◯": "O", "○": "O", "〇": "O", "⊙": "O", "⊕": "O",
    }
)


def poster_name(text: Any, *, limit: int = 42) -> str:
    """A name the poster's font can actually draw.

    Display names arrive in mathematical bold, fraktur, small caps and CJK —
    "𝚩𝚵𝚲𝐒𝚻 𝙂͓❍𝐇𝚲𝐍 〆「ビースト悟飯」" — and a Latin font draws every one of
    those as an empty box. The poster showed four tofu rectangles where the
    listener's name should be. NFKC flattens the styling, homoglyphs turn the
    Greek back into Latin, and anything left that the font cannot draw is
    dropped rather than printed as a box.
    """
    import unicodedata

    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.translate(_HOMOGLYPHS)
    kept = []
    for char in value:
        if char.isascii():
            kept.append(char)
        elif "\u0900" <= char <= "\u097f" or "\u0d00" <= char <= "\u0d7f":
            kept.append(char)             # the scripts we ship a font for
        elif char.isspace():
            kept.append(" ")
    cleaned = re.sub(r"\s+", " ", "".join(kept)).strip(" -·|")
    return cleaned[:limit].strip()


def display_line(title: Any, uploader: Any = "") -> str:
    """``Chris Grey - LET THE WORLD BURN`` (or just the name when it is alone)."""
    artist, name = display_parts(title, uploader)
    return f"{artist} - {name}" if artist and artist.lower() not in name.lower() else name


__all__ = [
    "DASHES",
    "clean_name",
    "display_line",
    "display_parts",
    "looks_like_artist",
    "poster_name",
]
