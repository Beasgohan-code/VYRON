# ---------------------------------------------------------------------------
#  VYRON — user playlists
#  Named collections of tracks saved per user; used by /saveplaylist and the
#  Library view in the web app.
# ---------------------------------------------------------------------------
from __future__ import annotations

import itertools
import re
import time
from typing import Any

from vyron.core.queue import Track
from vyron.runtime import runtime

MAX_PLAYLISTS = 40
_SEQ = itertools.count()
MAX_TRACKS = 200
_NAME_RE = re.compile(r"[^\w \-'.]+", re.UNICODE)


def clean_name(name: str, limit: int = 40) -> str:
    cleaned = _NAME_RE.sub("", str(name or "")).strip()
    return cleaned[:limit] or "Untitled"


def _storage():
    return runtime.storage


async def list_playlists(user_id: int) -> list[dict[str, Any]]:
    storage = _storage()
    if storage is None:
        return []
    return await storage.playlists(user_id)


async def create(user_id: int, name: str) -> dict[str, Any]:
    storage = _storage()
    if storage is None:
        raise RuntimeError("storage unavailable")
    existing = await storage.playlists(user_id)
    if len(existing) >= MAX_PLAYLISTS:
        raise ValueError(f"You already have {MAX_PLAYLISTS} playlists — delete one first.")
    entry = {
        "id": f"pl{int(time.time() * 1000)}{next(_SEQ) % 1000}",
        "name": clean_name(name),
        "tracks": [],
        "created": int(time.time()),
    }
    await storage.save_playlist(user_id, entry)
    return entry


async def delete(user_id: int, playlist_id: str) -> bool:
    storage = _storage()
    if storage is None:
        return False
    return await storage.delete_playlist(user_id, playlist_id)


async def find(user_id: int, ref: str) -> dict[str, Any] | None:
    ref = (ref or "").strip().lower()
    for playlist in await list_playlists(user_id):
        if playlist["id"] == ref or playlist["name"].lower() == ref:
            return playlist
    return None


async def add_tracks(user_id: int, playlist_id: str, tracks: list[Track]) -> int:
    storage = _storage()
    if storage is None:
        return 0
    playlist = next((p for p in await storage.playlists(user_id) if p["id"] == playlist_id), None)
    if playlist is None:
        return 0
    known = {str(entry.get("id")) for entry in playlist.get("tracks", [])}
    added = 0
    for track in tracks:
        if str(track.id) in known:
            continue
        if len(playlist["tracks"]) >= MAX_TRACKS:
            break
        playlist["tracks"].append({**track.to_dict(), "added": int(time.time())})
        known.add(str(track.id))
        added += 1
    await storage.save_playlist(user_id, playlist)
    return added


async def remove_track(user_id: int, playlist_id: str, media_id: str) -> bool:
    storage = _storage()
    if storage is None:
        return False
    playlist = next((p for p in await storage.playlists(user_id) if p["id"] == playlist_id), None)
    if playlist is None:
        return False
    before = len(playlist.get("tracks", []))
    playlist["tracks"] = [
        entry for entry in playlist.get("tracks", []) if str(entry.get("id")) != str(media_id)
    ]
    await storage.save_playlist(user_id, playlist)
    return len(playlist["tracks"]) != before


async def as_tracks(user_id: int, ref: str) -> tuple[str, list[Track]]:
    playlist = await find(user_id, ref)
    if playlist is None:
        return "", []
    return playlist["name"], [Track.from_dict(entry) for entry in playlist.get("tracks", [])]


def summary(playlist: dict[str, Any]) -> dict[str, Any]:
    tracks = playlist.get("tracks", [])
    covers = [entry.get("thumbnail") for entry in tracks if entry.get("thumbnail")][:4]
    return {
        "id": playlist["id"],
        "name": playlist["name"],
        "count": len(tracks),
        "duration": sum(int(entry.get("duration") or 0) for entry in tracks),
        "covers": covers,
        "created": playlist.get("created", 0),
        "tracks": [
            {
                "index": index,
                "id": entry.get("id"),
                "title": entry.get("title", ""),
                "uploader": entry.get("uploader", ""),
                "duration": int(entry.get("duration") or 0),
                "thumbnail": entry.get("thumbnail"),
                "query": f"{entry.get('title','')} {entry.get('uploader','')}".strip(),
            }
            for index, entry in enumerate(tracks, start=1)
        ],
    }


__all__ = [
    "MAX_PLAYLISTS",
    "MAX_TRACKS",
    "add_tracks",
    "as_tracks",
    "clean_name",
    "create",
    "delete",
    "find",
    "list_playlists",
    "remove_track",
    "summary",
]
