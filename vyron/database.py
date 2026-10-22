# ---------------------------------------------------------------------------
#  VYRON — persistence
#
#  MongoDB when MONGO_URL is configured, otherwise a JSON file that behaves
#  identically.  Every method is async so callers never care which backend is
#  active; pymongo calls are pushed to a worker thread.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from vyron.config import Settings

logger = logging.getLogger(__name__)


class Storage:
    backend = "unknown"

    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    # per-chat settings ------------------------------------------------
    async def chat_settings(self, chat_id: int) -> dict[str, Any]:
        return {}

    async def save_chat_settings(self, chat_id: int, data: dict[str, Any]) -> None: ...

    async def set_chat_setting(self, chat_id: int, key: str, value: Any) -> None:
        data = await self.chat_settings(chat_id)
        data[key] = value
        await self.save_chat_settings(chat_id, data)

    # favourites / history --------------------------------------------
    async def add_favorite(self, user_id: int, track: dict) -> bool:
        return False

    async def remove_favorite(self, user_id: int, media_id: str) -> bool:
        return False

    async def favorites(self, user_id: int, limit: int = 20) -> list[dict]:
        return []

    async def add_history(self, user_id: int, track: dict, limit: int = 30) -> None: ...

    async def history(self, user_id: int, limit: int = 10) -> list[dict]:
        return []

    # global counters --------------------------------------------------
    async def bump(self, key: str, amount: int = 1) -> None: ...

    async def counters(self) -> dict[str, int]:
        return {}

    async def all_chat_ids(self) -> list[int]:
        return []


# ── in-memory / JSON backend ────────────────────────────────────────────────
class JsonStorage(Storage):
    backend = "json"

    def __init__(self, settings: Settings) -> None:
        self.path = Path(settings.data_dir) / "vyron.json"
        self._data: dict[str, Any] = {
            "chats": {},
            "favorites": {},
            "history": {},
            "counters": {},
        }
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_file():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    self._data.update(stored)
            except Exception as exc:
                logger.warning("could not read %s: %s", self.path, exc)
        logger.info("storage: JSON file (%s)", self.path)

    async def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    async def save_chat_settings(self, chat_id: int, data: dict[str, Any]) -> None:
        async with self._lock:
            self._data["chats"][str(chat_id)] = data
            await self._flush()

    async def chat_settings(self, chat_id: int) -> dict[str, Any]:
        return dict(self._data["chats"].get(str(chat_id), {}))

    async def all_chat_ids(self) -> list[int]:
        return [int(k) for k in self._data["chats"].keys()]

    async def add_favorite(self, user_id: int, track: dict) -> bool:
        async with self._lock:
            items = self._data["favorites"].setdefault(str(user_id), [])
            media_id = str(track.get("id"))
            if any(str(i.get("id")) == media_id for i in items):
                return False
            track = {**track, "saved_at": int(time.time())}
            items.insert(0, track)
            del items[50:]
            await self._flush()
            return True

    async def remove_favorite(self, user_id: int, media_id: str) -> bool:
        async with self._lock:
            items = self._data["favorites"].setdefault(str(user_id), [])
            kept = [i for i in items if str(i.get("id")) != str(media_id)]
            changed = len(kept) != len(items)
            self._data["favorites"][str(user_id)] = kept
            if changed:
                await self._flush()
            return changed

    async def favorites(self, user_id: int, limit: int = 20) -> list[dict]:
        return self._data["favorites"].get(str(user_id), [])[:limit]

    async def add_history(self, user_id: int, track: dict, limit: int = 30) -> None:
        async with self._lock:
            items = self._data["history"].setdefault(str(user_id), [])
            items.insert(0, {**track, "played_at": int(time.time())})
            del items[limit:]
            await self._flush()

    async def history(self, user_id: int, limit: int = 10) -> list[dict]:
        return self._data["history"].get(str(user_id), [])[:limit]

    async def bump(self, key: str, amount: int = 1) -> None:
        async with self._lock:
            self._data["counters"][key] = int(self._data["counters"].get(key, 0)) + amount

    async def counters(self) -> dict[str, int]:
        return dict(self._data["counters"])


# ── MongoDB backend ─────────────────────────────────────────────────────────
class MongoStorage(Storage):
    backend = "mongo"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._db = None

    async def connect(self) -> None:
        from pymongo import MongoClient

        def _connect():
            client = MongoClient(self.settings.mongo_url, serverSelectionTimeoutMS=8000)
            client.admin.command("ping")
            return client

        self._client = await asyncio.to_thread(_connect)
        self._db = self._client[self.settings.mongo_db]
        await self._db.chats.create_index("chat_id", unique=True)
        await self._db.favorites.create_index([("user_id", 1), ("id", 1)])
        logger.info("storage: MongoDB (%s)", self.settings.mongo_db)

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)

    async def chat_settings(self, chat_id: int) -> dict[str, Any]:
        doc = await asyncio.to_thread(
            self._db.chats.find_one, {"chat_id": int(chat_id)}
        )
        if not doc:
            return {}
        doc.pop("_id", None)
        doc.pop("chat_id", None)
        return doc

    async def save_chat_settings(self, chat_id: int, data: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._db.chats.update_one,
            {"chat_id": int(chat_id)},
            {"$set": {**data, "chat_id": int(chat_id)}},
            True,
        )

    async def all_chat_ids(self) -> list[int]:
        cursor = await asyncio.to_thread(
            lambda: list(self._db.chats.find({}, {"chat_id": 1}))
        )
        return [int(doc["chat_id"]) for doc in cursor if "chat_id" in doc]

    async def add_favorite(self, user_id: int, track: dict) -> bool:
        media_id = str(track.get("id"))

        def _add():
            existing = self._db.favorites.find_one(
                {"user_id": int(user_id), "id": media_id}
            )
            if existing:
                return False
            self._db.favorites.update_one(
                {"user_id": int(user_id)},
                {
                    "$push": {
                        "items": {
                            "$each": [{**track, "saved_at": int(time.time())}],
                            "$position": 0,
                            "$slice": 50,
                        }
                    }
                },
                True,
            )
            return True

        return bool(await asyncio.to_thread(_add))

    async def remove_favorite(self, user_id: int, media_id: str) -> bool:
        result = await asyncio.to_thread(
            self._db.favorites.update_one,
            {"user_id": int(user_id)},
            {"$pull": {"items": {"id": str(media_id)}}},
        )
        return bool(result.modified_count)

    async def favorites(self, user_id: int, limit: int = 20) -> list[dict]:
        doc = await asyncio.to_thread(
            self._db.favorites.find_one, {"user_id": int(user_id)}
        )
        return (doc or {}).get("items", [])[:limit]

    async def add_history(self, user_id: int, track: dict, limit: int = 30) -> None:
        await asyncio.to_thread(
            self._db.history.update_one,
            {"user_id": int(user_id)},
            {
                "$push": {
                    "items": {
                        "$each": [{**track, "played_at": int(time.time())}],
                        "$position": 0,
                        "$slice": limit,
                    }
                }
            },
            True,
        )

    async def history(self, user_id: int, limit: int = 10) -> list[dict]:
        doc = await asyncio.to_thread(
            self._db.history.find_one, {"user_id": int(user_id)}
        )
        return (doc or {}).get("items", [])[:limit]

    async def bump(self, key: str, amount: int = 1) -> None:
        await asyncio.to_thread(
            self._db.counters.update_one,
            {"_id": key},
            {"$inc": {"value": amount}},
            True,
        )

    async def counters(self) -> dict[str, int]:
        docs = await asyncio.to_thread(lambda: list(self._db.counters.find({})))
        return {doc["_id"]: int(doc.get("value", 0)) for doc in docs}


async def make_storage(settings: Settings) -> Storage:
    if settings.mongo_url:
        try:
            storage = MongoStorage(settings)
            await storage.connect()
            return storage
        except Exception as exc:
            logger.warning("MongoDB unavailable (%s) — falling back to JSON storage", exc)
    storage = JsonStorage(settings)
    await storage.connect()
    return storage


__all__ = ["JsonStorage", "MongoStorage", "Storage", "make_storage"]
