# ---------------------------------------------------------------------------
#  VYRON — autoplay that keeps the mood, not just the genre
# ---------------------------------------------------------------------------
# The first version of autoplay asked YouTube for "related" tracks and queued
# the first one it had not played yet. That works for a song with good
# neighbours and sounds like a random shuffle for anything else — a Malayalam
# melody followed by a gaming montage, a lofi loop followed by a podcast.
#
# This module is the missing half, ported from ShizuMusic's autoplay engine:
#
#   · **clean titles**  "Song (Official Video) ft. X [4K]" → "Song"
#   · **mood + language** per chat, so a queue stays in one lane
#   · **candidate spam** several short queries instead of one big one, because
#     YouTube's *search* is far more predictable than its related-videos graph
#   · **de-duplication** against everything already played this session, by id
#     *and* by normalised title (the same song uploaded twice is the same song)
#
# Everything is plain functions over ``Track`` objects so it can be tested
# without a network or a client.
from __future__ import annotations

import logging
import random
import re
from typing import Iterable

from vyron.core.queue import Track

logger = logging.getLogger(__name__)

# how many search results to look at per query
SEARCH_LIMIT = 8
# candidates below this are almost always intros/shorts, not music
MIN_SECONDS = 45
MAX_SECONDS = 900

MOODS: dict[str, str] = {
    "chill": "lofi chill relaxing",
    "focus": "instrumental study focus",
    "party": "party dance hits",
    "romantic": "romantic love songs",
    "workout": "workout gym energy",
    "sad": "sad emotional songs",
    "sleep": "sleep ambient calm",
    "drive": "night drive songs",
}
LANGUAGES: dict[str, str] = {
    "english": "english",
    "hindi": "hindi songs",
    "malayalam": "malayalam songs",
    "tamil": "tamil songs",
    "telugu": "telugu songs",
    "kannada": "kannada songs",
    "punjabi": "punjabi songs",
    "bengali": "bengali songs",
    "urdu": "urdu songs",
}

# noise that survives in YouTube titles and ruins a search query
_NOISE = re.compile(
    r"\s*(?:[\(\[]\s*(?:official|lyric|lyrics|video|audio|music video|mv|m/v|hd|4k|8k|remaster(?:ed)?|"
    r"visualizer|performance|live|full song|full video|song|teaser|trailer|promo)\b[^\)\]]*[\)\]])",
    re.I,
)
_FEAT = re.compile(r"\s+(?:ft\.?|feat\.?|featuring)\s+[^,|\[\]\(\)]+", re.I)
_TAIL = re.compile(r"\s*[-|–—]\s*(?:official|lyrical|video|audio|music).*$", re.I)
_PIPE = re.compile(r"\s*[|•·]\s*.*$")
# markers that make a "version" a different recording, not a re-upload
_EXTRA_MARKERS = re.compile(
    r"\b(?:remix|lofi|slowed|reverb|extended|mix|edit|cover|acoustic|instrumental|8d|nightcore|sped)\b",
    re.I,
)
_BAD_WORDS = re.compile(
    r"\b(?:karaoke|cover|instrumental|slowed|reverb|8d|nightcore|reaction|gameplay|"
    r"walkthrough|shorts|tutorial|trailer|review|podcast|interview)\b",
    re.I,
)


def clean_title(title: str) -> str:
    """``Song (Official Video) ft. X | Label`` → ``Song``."""
    text = (title or "").strip()
    if not text:
        return ""
    text = _PIPE.sub("", text)
    text = _FEAT.sub("", text)
    text = _NOISE.sub("", text)
    text = _TAIL.sub("", text)
    # collapse leftover brackets like "(Remastered 2011)"
    text = re.sub(r"\s*[\(\[]\s*[\)\]]", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—|·")
    return text[:120]


def normalise(title: str) -> str:
    """Aggressive form used for de-duplication, not for searching."""
    text = clean_title(title).lower()
    text = re.sub(r"[^a-z0-9\u0900-\u097f\u0d00-\u0d7f ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def same_song(one: str, other: str) -> bool:
    """Two titles that are the same recording (upload, label, remaster)."""
    a, b = normalise(one), normalise(other)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) < 8 or shorter not in longer:
        return False
    # "kesariya" is inside "kesariya lofi remix extended", but that is a
    # different recording — only accept a re-upload, not a re-work.
    if len(shorter) / len(longer) < 0.6:
        return False
    return not _EXTRA_MARKERS.search(longer.replace(shorter, " "))


def usable(title: str, duration: int) -> bool:
    """Filter out shorts, karaoke, gameplay and hour-long mixes."""
    if duration and not (MIN_SECONDS <= duration <= MAX_SECONDS):
        return False
    return not _BAD_WORDS.search(title or "")


def build_queries(seed_title: str, *, mood: str = "", language: str = "", artist: str = "") -> list[str]:
    """Short, specific searches — best first.

    YouTube matches a 4-word query far more reliably than a 12-word one, and
    asking for ``artist + song`` before ``mood`` keeps the first suggestion
    close to what is playing.
    """
    cleaned = clean_title(seed_title)
    parts: list[str] = []
    mood_text = MOODS.get(mood, "")
    lang_text = LANGUAGES.get(language, "")

    # An explicit lane comes first: if a chat asked for Malayalam, the very
    # first search has to stay inside it. Breadth ("artist", "song") follows.
    if cleaned and lang_text:
        parts.append(f"{cleaned} {lang_text}")
    if cleaned and mood_text:
        parts.append(f"{cleaned} {mood_text}")
    if cleaned and artist:
        parts.append(f"{cleaned} {artist}")
    if cleaned:
        parts.append(f"{cleaned} song")
    if mood_text and lang_text:
        parts.append(f"{mood_text} {lang_text}")
    elif mood_text:
        parts.append(mood_text)
    elif lang_text:
        parts.append(f"best {lang_text}")

    # de-duplicate while keeping order
    seen: set[str] = set()
    queries: list[str] = []
    for query in parts:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            queries.append(query)
    return queries


def _soft_shuffle(items: list[Track], group: int = 3) -> list[Track]:
    """Shuffle inside small blocks — related-first order, never the same chain.

    Straight `random.choice` over the whole pool turns autoplay into a lottery;
    taking the top result every time walks the same chain forever. Shuffling in
    threes keeps the search's relevance ranking and drops the predictability
    (the idea comes from ShizuMusic's autoplay buffer).
    """
    out: list[Track] = []
    for start in range(0, len(items), max(1, group)):
        chunk = items[start : start + max(1, group)]
        random.shuffle(chunk)
        out.extend(chunk)
    return out


def pick(
    candidates: Iterable[Track],
    *,
    played: Iterable[Track] = (),
    seed_title: str = "",
    seed_artist: str = "",
    group: int = 3,
    streak_artists: Iterable[str] = (),
) -> Track | None:
    """The first candidate that is not the same song as anything played."""
    known = list(played)
    seed = normalise(seed_title) if seed_title else ""

    def fresh(candidate: Track) -> bool:
        if not candidate.id:
            return False
        if candidate.title and not usable(candidate.title, candidate.duration):
            return False
        if seed and same_song(candidate.title, seed_title):
            return False
        for old in known:
            if old.id and old.id == candidate.id:
                return False
            if old.title and same_song(candidate.title, old.title):
                return False
        return True

    pool = [c for c in candidates if fresh(c)]
    if not pool:
        return None
    # Rotate the artist: five songs by the same person in a row is the other
    # way autoplay feels broken. Only enforced while there is real choice.
    seed_by = (seed_artist or "").strip().lower()
    if seed_by:
        varied = [
            c for c in pool if (getattr(c, "uploader", "") or "").strip().lower() != seed_by
        ]
        if len(varied) >= 2:
            pool = varied

    # …and the same rule for an artist the room has just heard twice.
    tired = {(name or "").strip().lower() for name in streak_artists if name}
    if tired:
        fresh_artists = [
            c for c in pool if (getattr(c, "uploader", "") or "").strip().lower() not in tired
        ]
        if len(fresh_artists) >= 2:
            pool = fresh_artists
    shuffled = _soft_shuffle(pool[:9], group=group)
    return shuffled[0] if shuffled else pool[0]


async def next_track(
    youtube,
    seed: Track,
    *,
    mood: str = "",
    language: str = "",
    played: Iterable[Track] = (),
    streak_artists: Iterable[str] = (),
) -> Track | None:
    """Search the mood/language lane and return one track, or ``None``."""
    if youtube is None or seed is None:
        return None
    seen = list(played)
    queries = build_queries(seed.title, mood=mood, language=language, artist=seed.uploader or "")
    for query in queries[:3]:
        try:
            results = await youtube.search(query, limit=SEARCH_LIMIT)
        except Exception as exc:  # pragma: no cover - network paths
            logger.debug("autoplay search failed for %r: %s", query, exc)
            continue
        chosen = pick(
            results,
            played=seen,
            seed_title=seed.title,
            seed_artist=seed.uploader or "",
            streak_artists=streak_artists,
        )
        if chosen is not None:
            chosen.requested_name = "autoplay"
            logger.info("autoplay picked %r for %r", chosen.title, seed.title)
            return chosen
    return None


def describe(mood: str, language: str) -> str:
    """Human line for the settings card: ``lofi chill · hindi songs``."""
    bits = []
    if mood:
        bits.append(MOODS.get(mood, mood))
    if language:
        bits.append(LANGUAGES.get(language, language))
    return " · ".join(bits)


__all__ = [
    "LANGUAGES",
    "MOODS",
    "build_queries",
    "clean_title",
    "describe",
    "next_track",
    "normalise",
    "pick",
    "same_song",
    "usable",
]
