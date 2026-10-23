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

    # maintenance -------------------------------------------------------
    async def prune(self, days: int = 30) -> dict[str, int]:
        """Drop history/favourite rows older than *days*."""
        return {"history": 0, "favorites": 0}

    async def all_chat_ids(self) -> list[int]:
        return []

    # music-API keys ---------------------------------------------------
    async def api_keys(self, owner_id: int | None = None) -> list[dict]:
        return []

    async def add_api_key(self, record: dict) -> None: ...

    async def update_api_key(self, key: str, patch: dict) -> bool:
        return False

    async def bump_api_key(self, key: str, *, uses: int = 1, size: int = 0, stamp: float | None = None) -> None:
        return None

    # playlists --------------------------------------------------------
    async def playlists(self, user_id: int) -> list[dict]:
        return []

    async def save_playlist(self, user_id: int, playlist: dict) -> None: ...

    async def delete_playlist(self, user_id: int, playlist_id: str) -> bool:
        return False


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
            "playlists": {},
            "api_keys": {},
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

    async def playlists(self, user_id: int) -> list[dict]:
        return [dict(item) for item in self._data.setdefault("playlists", {}).get(str(user_id), [])]

    async def save_playlist(self, user_id: int, playlist: dict) -> None:
        async with self._lock:
            bucket = self._data.setdefault("playlists", {}).setdefault(str(user_id), [])
            for index, item in enumerate(bucket):
                if item.get("id") == playlist.get("id"):
                    bucket[index] = playlist
                    break
            else:
                bucket.insert(0, playlist)
            await self._flush()

    async def delete_playlist(self, user_id: int, playlist_id: str) -> bool:
        async with self._lock:
            bucket = self._data.setdefault("playlists", {}).setdefault(str(user_id), [])
            kept = [item for item in bucket if item.get("id") != playlist_id]
            changed = len(kept) != len(bucket)
            self._data["playlists"][str(user_id)] = kept
            if changed:
                await self._flush()
            return changed

    async def api_keys(self, owner_id: int | None = None) -> list[dict]:
        keys = [dict(item) for item in self._data.get("api_keys", {}).values()]
        if owner_id is not None:
            keys = [item for item in keys if int(item.get("owner_id", 0)) == int(owner_id)]
        return sorted(keys, key=lambda item: item.get("created_at") or 0, reverse=True)

    # API keys are stored under their opaque `id` (never the raw key, which is
    # only ever held as a SHA-256 hash).  Legacy plaintext records written by
    # older builds are still readable because the lookup falls back to a scan.
    @staticmethod
    def _key_ref(record: dict) -> str:
        return str(record.get("id") or record.get("hash") or record.get("key") or record.get("prefix") or "")

    def _find_key(self, bucket: dict, reference: str) -> dict | None:
        reference = str(reference or "")
        if not reference:
            return None
        if reference in bucket:
            return bucket[reference]
        for record in bucket.values():
            if reference in {str(record.get("id") or ""), str(record.get("prefix") or ""),
                             str(record.get("hash") or ""), str(record.get("key") or "")}:
                return record
        return None

    async def add_api_key(self, record: dict) -> None:
        async with self._lock:
            bucket = self._data.setdefault("api_keys", {})
            reference = self._key_ref(record)
            # migrate a legacy plaintext row in place instead of duplicating it
            existing = self._find_key(bucket, reference) or self._find_key(bucket, str(record.get("key") or ""))
            if existing is not None and existing is not bucket.get(reference):
                bucket.pop(str(existing.get("key") or existing.get("id") or ""), None)
            bucket[reference] = dict(record)
            await self._flush()

    async def update_api_key(self, key: str, patch: dict) -> bool:
        async with self._lock:
            bucket = self._data.setdefault("api_keys", {})
            record = self._find_key(bucket, key)
            if record is None:
                return False
            record.update(patch)
            await self._flush()
            return True

    async def bump_api_key(self, key: str, *, uses: int = 1, size: int = 0, stamp: float | None = None) -> None:
        async with self._lock:
            record = self._find_key(self._data.setdefault("api_keys", {}), key)
            if record is None:
                return
            record["uses"] = int(record.get("uses") or 0) + int(uses)
            record["bytes"] = int(record.get("bytes") or 0) + max(0, int(size))
            record["last_used_at"] = stamp or time.time()
            await self._flush()

    async def prune(self, days: int = 30) -> dict[str, int]:
        cutoff = time.time() - max(0, int(days)) * 86400
        removed = {"history": 0, "favorites": 0}
        async with self._lock:
            for bucket, stamp in (("history", "played_at"), ("favorites", "saved_at")):
                store = self._data.get(bucket, {})
                for user_id in list(store):
                    items = store[user_id] or []
                    kept = [
                        item
                        for item in items
                        if not item.get(stamp) or int(item.get(stamp, 0)) >= cutoff
                    ]
                    removed[bucket] += len(items) - len(kept)
                    if kept:
                        store[user_id] = kept
                    else:
                        store.pop(user_id, None)
            if any(removed.values()):
                await self._flush()
        return removed

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

        raw = (self.settings.mongo_url or "").strip()
        if not raw.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError(
                "MONGO_URL must start with mongodb:// or mongodb+srv:// "
                "(copy the whole connection string from Atlas)"
            )

        def _connect():
            client = MongoClient(
                raw,
                serverSelectionTimeoutMS=8000,
                connectTimeoutMS=8000,
                socketTimeoutMS=20000,
                # Atlas free tier is reachable from Render, but DNS SRV lookups
                # occasionally fail on cold start — retry once before giving up.
                retryWrites=True,
            )
            client.admin.command("ping")
            return client

        self._client = await asyncio.to_thread(_connect)
        self._db = self._client[self.settings.mongo_db]
        # pymongo's create_index is synchronous — it returns the index *name*,
        # so awaiting it directly raises "object str can't be used in 'await'".
        await asyncio.to_thread(self._ensure_indexes)
        logger.info("storage: MongoDB (%s)", self.settings.mongo_db)

    def _ensure_indexes(self) -> None:
        self._db.chats.create_index("chat_id", unique=True)
        self._db.favorites.create_index([("user_id", 1)])
        self._db.history.create_index([("user_id", 1)])
        self._db.playlists.create_index([("user_id", 1)])
        # Keys are stored by opaque id; the raw key never touches the database.
        # Index problems must never block a boot, so each step is guarded.
        try:
            self._db.api_keys.drop_index("key_1")  # legacy plaintext index
        except Exception:
            pass
        try:
            self._db.api_keys.create_index("id", unique=True, sparse=True)
            self._db.api_keys.create_index("prefix")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("api_keys indexes not created: %s", exc)

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

    async def playlists(self, user_id: int) -> list[dict]:
        doc = await asyncio.to_thread(
            self._db.playlists.find_one, {"user_id": int(user_id)}
        )
        return list((doc or {}).get("items", []))

    async def save_playlist(self, user_id: int, playlist: dict) -> None:
        def _save():
            doc = self._db.playlists.find_one({"user_id": int(user_id)}) or {}
            items = {item["id"]: item for item in doc.get("items", [])}
            items[playlist["id"]] = playlist
            ordered = sorted(items.values(), key=lambda item: item.get("created", 0), reverse=True)
            self._db.playlists.update_one(
                {"user_id": int(user_id)},
                {"$set": {"items": ordered[:40]}},
                True,
            )

        await asyncio.to_thread(_save)

    async def delete_playlist(self, user_id: int, playlist_id: str) -> bool:
        result = await asyncio.to_thread(
            self._db.playlists.update_one,
            {"user_id": int(user_id)},
            {"$pull": {"items": {"id": playlist_id}}},
        )
        return bool(result.modified_count)

    async def prune(self, days: int = 30) -> dict[str, int]:
        cutoff = int(time.time() - max(0, int(days)) * 86400)

        def _prune():
            removed = {"history": 0, "favorites": 0}
            for collection, stamp in (
                (self._db.history, "played_at"),
                (self._db.favorites, "saved_at"),
            ):
                result = collection.update_many(
                    {},
                    {"$pull": {"items": {stamp: {"$lt": cutoff}}}},
                )
                removed[collection.name] = int(result.modified_count)
            return removed

        return await asyncio.to_thread(_prune)

    # ── API keys ───────────────────────────────────────────────────────────
    async def api_keys(self, owner_id: int | None = None) -> list[dict]:
        query = {} if owner_id is None else {"owner_id": int(owner_id)}

        def _load() -> list[dict]:
            rows = []
            for doc in self._db.api_keys.find(query):
                doc.pop("_id", None)
                rows.append(doc)
            return sorted(rows, key=lambda item: item.get("created_at") or 0, reverse=True)

        return await asyncio.to_thread(_load)

    async def add_api_key(self, record: dict) -> None:
        reference = str(record.get("id") or record.get("hash") or record.get("key") or "")
        if not reference:
            raise ValueError("api key record needs an id")

        def _save():
            self._db.api_keys.update_one(
                {"_id": reference}, {"$set": {**record, "_id": reference}}, True
            )

        await asyncio.to_thread(_save)

    @staticmethod
    def _key_query(reference: str) -> dict:
        return {"$or": [{"_id": reference}, {"id": reference}, {"prefix": reference}, {"hash": reference}, {"key": reference}]}

    async def update_api_key(self, key: str, patch: dict) -> bool:
        def _update():
            result = self._db.api_keys.update_one(self._key_query(str(key)), {"$set": patch})
            return bool(result.modified_count or result.matched_count)

        return bool(await asyncio.to_thread(_update))

    async def bump_api_key(self, key: str, *, uses: int = 1, size: int = 0, stamp: float | None = None) -> None:
        def _bump():
            self._db.api_keys.update_one(
                self._key_query(str(key)),
                {
                    "$inc": {"uses": int(uses), "bytes": max(0, int(size))},
                    "$set": {"last_used_at": stamp or time.time()},
                },
            )

        await asyncio.to_thread(_bump)

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
            logger.warning(
                "MongoDB unavailable (%s) — falling back to JSON storage. "
                "Check MONGO_URL/MONGO_DB and that this host can reach the cluster "
                "(Atlas → Network Access).",
                exc,
            )
    storage = JsonStorage(settings)
    await storage.connect()
    return storage


__all__ = ["JsonStorage", "MongoStorage", "Storage", "make_storage"]
