# ---------------------------------------------------------------------------
#  VYRON — autoplay that keeps the mood, not just the genre
# ---------------------------------------------------------------------------
# The first version of autoplay asked YouTube for "related" tracks and queued
# the first one it had not played yet. That works for a song with good
# neighbours and sounds like a random shuffle for anything else — a Malayalam
# melody followed by a gaming montage, a lofi loop followed by a podcast.
#
# This module is the missing half. What it adds, in the order it matters:
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

import asyncio
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

#: Words that keep a pick inside the chat's chosen mood. They are a
#: *preference*, never a filter: an empty lane is how autoplay dies, so a
#: non-matching track is always still a candidate — just later in the pool.
MOOD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "chill": ("chill", "relax", "lofi", "lo-fi", "acoustic", "unplugged", "soft", "ambient"),
    "focus": ("instrumental", "study", "focus", "piano", "concentration", "lofi"),
    "party": ("party", "club", "dance", "dj", "remix", "bass", "nacho", "bhangra"),
    "romantic": ("love", "pyaar", "ishq", "mohabbat", "romantic", "dil", "sanam", "heart"),
    "workout": ("workout", "gym", "motivation", "energy", "power", "fitness", "beast"),
    "sad": ("sad", "dard", "judaa", "tanha", "alone", "broken", "tears", "heartbreak"),
    "sleep": ("sleep", "ambient", "calm", "rain", "lullaby", "insomnia"),
    "drive": ("drive", "night", "highway", "road", "travel", "ride"),
}

#: Language words as they actually appear in uploads. Every entry is optional
#: in a title — most Hindi uploads never say "Hindi", which is why that lane is
#: handled by *excluding* the other Indian languages instead.
LANGUAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "english": ("english", "pop", "rock", "hip hop", "indie"),
    "hindi": ("hindi", "bollywood", "filmi"),
    "malayalam": ("malayalam", "mollywood"),
    "tamil": ("tamil", "kollywood"),
    "telugu": ("telugu", "tollywood"),
    "kannada": ("kannada", "sandalwood"),
    "punjabi": ("punjabi", "jatt", "bhangra", "munde", "kudi"),
    "bengali": ("bengali", "bangla"),
    "urdu": ("urdu", "pakistani", "ghazal"),
}
OTHER_INDIAN = (
    "punjabi", "tamil", "telugu", "kannada", "malayalam",
    "bengali", "marathi", "gujarati", "bhojpuri", "haryanvi",
)

#: Stop widening the pool once there is real choice — every extra query is a
#: network round trip in the gap before the next song.
POOL_ENOUGH = 8

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


def lane_match(track: Track, *, mood: str = "", language: str = "") -> int:
    """How well *track* fits the lane: 0, 1 (mood or language), or 2.

    Reads the title and the channel, because that is where uploads put it —
    "Kesariya (Hindi)" in the title, "T-Series" in the channel.
    """
    text = f"{getattr(track, 'title', '') or ''} {getattr(track, 'uploader', '') or ''}".lower()
    score = 0
    if mood:
        words = MOOD_KEYWORDS.get(mood, ())
        if words and any(word in text for word in words):
            score += 1
    if language:
        if language == "hindi":
            if not any(word in text for word in OTHER_INDIAN):
                score += 1
        else:
            words = LANGUAGE_KEYWORDS.get(language, ())
            if words and any(word in text for word in words):
                score += 1
    return score


def prefer_lane(
    tracks: Iterable[Track], *, mood: str = "", language: str = ""
) -> list[Track]:
    """Stable partition: lane matches first, everything else right behind.

    A hard filter looks tidier and is worse in practice — on a query that
    returns nothing in the lane it empties the pool and autoplay stops, which
    is the one thing it must never do.
    """
    items = list(tracks)
    if not mood and not language:
        return items
    matches = [item for item in items if lane_match(item, mood=mood, language=language)]
    rest = [item for item in items if item not in matches]
    return matches + rest


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
    (a small buffer of scored candidates, refreshed as the queue drains).
    """
    out: list[Track] = []
    for start in range(0, len(items), max(1, group)):
        chunk = items[start : start + max(1, group)]
        random.shuffle(chunk)
        out.extend(chunk)
    return out


def _grouped_shuffle(
    items: list[Track], keys: dict[int, int], limit: int = 9
) -> list[Track]:
    """Best-ranked first; variety inside a rank, never across one.

    This is the difference between "a lane" and "a lottery": two candidates
    that fit the mood and language equally well are interchangeable, but a
    candidate from a *different* lane is not a fair swap for one from this
    one. Blindly shuffling the top three (what this used to do) put a gaming
    montage ahead of the Malayalam track it had just found.
    """
    ordered = sorted(items, key=lambda item: -keys.get(id(item), 0))
    out: list[Track] = []
    index = 0
    while index < len(ordered):
        rank = keys.get(id(ordered[index]), 0)
        block: list[Track] = []
        while index < len(ordered) and keys.get(id(ordered[index]), 0) == rank:
            block.append(ordered[index])
            index += 1
        random.shuffle(block)
        out.extend(block)
    return out[:limit]


def pick(
    candidates: Iterable[Track],
    *,
    played: Iterable[Track] = (),
    seed_title: str = "",
    seed_artist: str = "",
    group: int = 3,
    streak_artists: Iterable[str] = (),
    keys: Iterable[int] | None = None,
) -> Track | None:
    """The first candidate that is not the same song as anything played.

    ``keys`` (one per candidate, higher = better) switches the shuffle from
    "blocks of three" to "within a rank": the caller uses it for the mood and
    language lane.
    """
    known = list(played)
    seed = normalise(seed_title) if seed_title else ""
    items = list(candidates)
    rank: dict[int, int] | None = None
    if keys is not None:
        pairs = list(zip(items, keys, strict=False))
        if len(pairs) == len(items):
            rank = {id(item): int(value) for item, value in pairs}

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

    pool = [c for c in items if fresh(c)]
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
    if rank is not None:
        ranked = _grouped_shuffle(pool, rank)
        return ranked[0] if ranked else pool[0]
    shuffled = _soft_shuffle(pool[:9], group=group)
    return shuffled[0] if shuffled else pool[0]


async def candidates(
    youtube,
    seed: Track,
    *,
    mood: str = "",
    language: str = "",
    limit: int = 15,
    budget_seconds: float = 30.0,
) -> list[Track]:
    """Everywhere a next song can come from — one pool, best sources first.

    YouTube's *related* graph is what makes a queue feel hand-picked ("more
    like this"), and search is what keeps it in the lane ("more Malayalam
    like this"). Using only one of them is the bug: related alone drifts out of
    the lane, search alone walks the same chain of near-duplicates. The first
    two lookups run together; further queries are only spent while the pool is
    still thin, so the common case is one round trip, not five.
    """
    if youtube is None or seed is None:
        return []

    pool: list[Track] = []
    seen: set[str] = set()

    def add(items) -> None:
        for item in items or ():
            key = str(getattr(item, "id", "") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            pool.append(item)

    queries = build_queries(seed.title, mood=mood, language=language, artist=seed.uploader or "")
    related = getattr(youtube, "related", None)
    started = asyncio.get_event_loop().time()

    first = []
    if callable(related):
        first.append(related(seed, limit=limit))
    if queries:
        first.append(youtube.search(queries[0], limit=SEARCH_LIMIT))
    if first:
        for result in await asyncio.gather(*first, return_exceptions=True):
            if isinstance(result, BaseException):
                logger.debug("autoplay source failed: %s", result)
                continue
            add(result)

    for query in queries[1:3]:
        if len(pool) >= POOL_ENOUGH:
            break
        if asyncio.get_event_loop().time() - started > budget_seconds:
            logger.debug("autoplay pool timed out after %d candidate(s)", len(pool))
            break
        try:
            add(await youtube.search(query, limit=SEARCH_LIMIT))
        except Exception as exc:  # pragma: no cover - network paths
            logger.debug("autoplay search failed for %r: %s", query, exc)
    return pool


async def next_track(
    youtube,
    seed: Track,
    *,
    mood: str = "",
    language: str = "",
    played: Iterable[Track] = (),
    streak_artists: Iterable[str] = (),
) -> Track | None:
    """One next track from the lane's whole candidate pool, or ``None``."""
    if youtube is None or seed is None:
        return None
    pool = await candidates(youtube, seed, mood=mood, language=language)
    if not pool:
        return None
    ordered = prefer_lane(pool, mood=mood, language=language)
    chosen = pick(
        ordered,
        played=list(played),
        seed_title=seed.title,
        seed_artist=seed.uploader or "",
        streak_artists=streak_artists,
        keys=[lane_match(item, mood=mood, language=language) for item in ordered],
    )
    if chosen is None:
        return None
    chosen.requested_name = "autoplay"
    logger.info("autoplay picked %r for %r", chosen.title, seed.title)
    return chosen


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
    "LANGUAGE_KEYWORDS",
    "MOODS",
    "MOOD_KEYWORDS",
    "build_queries",
    "candidates",
    "clean_title",
    "describe",
    "lane_match",
    "next_track",
    "normalise",
    "pick",
    "prefer_lane",
    "same_song",
    "usable",
]
