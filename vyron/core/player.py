# ---------------------------------------------------------------------------
#  VYRON — player engine
#
#  Owns the voice-chat lifecycle: resolving a stream, handing it to PyTgCalls,
#  advancing the queue on stream-end, keeping the now-playing card fresh and
#  leaving an idle voice chat so the assistant never lingers.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any

from pytgcalls import PyTgCalls
from pytgcalls import filters as fl
from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError
from pytgcalls.types import AudioQuality, GroupCallConfig, MediaStream, VideoQuality

from vyron.config import Settings
from vyron.core import effects as audio_fx
from vyron.core.queue import ChatState, LoopMode, QueueManager, Track
from vyron.core.sources import DIRECT_SOURCES as _DIRECT_SOURCES
from vyron.core.sources import EXTRACT_SOURCES as _EXTRACT_SOURCES
from vyron.core.search import MediaError, YouTube
from vyron.database import Storage
from vyron.core.journal import journal
from vyron.ui import cards, keyboards, nowplaying, rich
from vyron.ui.progress import now as clock

logger = logging.getLogger(__name__)

# Every queue and every setting that matters is mirrored into one meta document
# so a restart (or a Render redeploy) does not throw away what people queued.
_QUEUE_META = "queues"
_SAVE_DELAY = 1.5


#: Extensions a browser (and ntgcalls) will treat as pictures, not sound.
_VIDEO_EXTS = {"mp4", "webm", "mkv", "mov", "m4v"}


def _is_video_stream(info) -> bool:
    """True when *info* actually carries a picture, not just audio.

    Substitutions (JioSaavn, Audius, SoundCloud) are audio-only no matter what
    was asked for, and their ``mime`` says so.
    """
    mime = str(getattr(info, "mime", "") or "").lower()
    if mime.startswith("video/"):
        return True
    if mime.startswith("audio/"):
        return False
    return str(getattr(info, "ext", "") or "").lower() in _VIDEO_EXTS


def _is_local_file(url: str) -> bool:
    """Is this a path we already downloaded? A stat, so stay synchronous."""
    try:
        return bool(url) and Path(url).is_file()
    except OSError:
        return False


class StreamError(RuntimeError):
    """Playback could not be started; message is user-presentable."""


def _audio_quality(name: str) -> AudioQuality:
    return {
        "low": AudioQuality.LOW,
        "medium": AudioQuality.MEDIUM,
        "high": AudioQuality.HIGH,
    }.get(str(name).lower(), AudioQuality.HIGH)


def _video_quality(name: str) -> VideoQuality:
    return {
        "360p": VideoQuality.SD_360p,
        "480p": VideoQuality.SD_480p,
        "720p": VideoQuality.HD_720p,
        "1080p": VideoQuality.FHD_1080p,
    }.get(str(name).lower(), VideoQuality.HD_720p)


class Player:
    def __init__(
        self,
        bot: Any,
        calls: PyTgCalls | None,
        settings: Settings,
        storage: Storage,
        youtube: YouTube,
        assistant: Any = None,
        downloader: Any = None,
    ) -> None:
        self.bot = bot
        self.calls = calls
        self.settings = settings
        self.storage = storage
        self.youtube = youtube
        # The userbot that actually joins voice chats. Needed to *open* a voice
        # chat that nobody has started yet, which is the single most common
        # reason a first /play fails.
        self.assistant = assistant
        # optional: when set (and PLAY_FROM_DISK is on) tracks are downloaded
        # once and streamed from the cache — the ShizuMusic model
        self.downloader = downloader
        self.queues = QueueManager(settings.default_volume, settings.autoplay_default)

        self._locks: dict[int, asyncio.Lock] = {}
        self._np_tasks: dict[int, asyncio.Task] = {}
        self._prefetch_tasks: dict[int, asyncio.Task] = {}
        self._settings_loaded: set[int] = set()
        self._vc_attempts: dict[int, float] = {}
        self._save_task: asyncio.Task | None = None
        self._in_call: set[int] = set()
        # last mid-song recovery per chat: a drop is retried once, not forever
        self._recovered_at: dict[int, float] = {}
        self._idle_task: asyncio.Task | None = None
        self._running = False
        self.tracks_played = 0
        self._empty_checks: dict[int, int] = {}

    # ── infrastructure ─────────────────────────────────────────────────────
    @property
    def streaming(self) -> bool:
        return self.calls is not None

    def lock(self, chat_id: int) -> asyncio.Lock:
        return self._locks.setdefault(int(chat_id), asyncio.Lock())

    def active_chats(self) -> list[int]:
        return [chat_id for chat_id in self._in_call]

    async def restore_settings(self, chat_id: int) -> ChatState:
        state = self.queues.get(chat_id)
        if int(chat_id) in self._settings_loaded:
            return state
        data = await self.storage.chat_settings(chat_id)
        self._settings_loaded.add(int(chat_id))
        if data:
            state.loop = LoopMode.parse(data.get("loop", state.loop.value))
            state.autoplay = bool(data.get("autoplay", state.autoplay))
            state.volume = int(data.get("volume", state.volume) or state.volume)
            state.always_on = bool(data.get("always_on", state.always_on))
            state.effects = audio_fx.resolve(data.get("effects", []))
            state.mood = str(data.get("mood", state.mood) or "")
            state.language = str(data.get("language", state.language) or "")
        return state

    async def persist(self, chat_id: int) -> None:
        state = self.queues.get(chat_id)
        await self.storage.save_chat_settings(
            chat_id,
            {
                "loop": state.loop.value,
                "autoplay": state.autoplay,
                "volume": state.volume,
                "always_on": state.always_on,
                "mood": state.mood,
                "language": state.language,
            },
        )

    # ── queue persistence ──────────────────────────────────────────────────
    def snapshot(self) -> dict[str, dict]:
        """Everything needed to rebuild the queues after a restart."""
        data: dict[str, dict] = {}
        for state in self.queues.all():
            if not state.current and not state.queue:
                continue
            data[str(state.chat_id)] = {
                "queue": [track.to_dict() for track in state.queue],
                "current": state.current.to_dict() if state.current else None,
                # Where playback had reached. A queue that comes back at 0:00
                # is a queue the listener has to scrub through again.
                "position": round(state.elapsed(), 1) if state.current else 0.0,
                "loop": state.loop.value,
                "autoplay": state.autoplay,
                "shuffle": state.shuffle,
                "volume": state.volume,
                "always_on": state.always_on,
                "effects": list(state.effects),
                "mood": state.mood,
                "language": state.language,
            }
        return data

    def schedule_save(self) -> None:
        """Write the queues back a moment later (coalesces bursts of changes)."""
        if not self.storage:
            return
        if self._save_task and not self._save_task.done():
            return
        try:
            self._save_task = asyncio.create_task(self._save_worker())
        except RuntimeError:  # pragma: no cover - no running loop
            pass

    async def _save_worker(self) -> None:
        try:
            await asyncio.sleep(_SAVE_DELAY)
            data = self.snapshot()
            if data:
                await self.storage.set_meta(_QUEUE_META, data)
            else:
                await self.storage.set_meta(_QUEUE_META, {})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # persistence is best effort, never fatal
            logger.debug("queue snapshot failed: %s", exc)

    async def restore_queues(self) -> int:
        """Rebuild the queues from the last snapshot.

        Audio cannot resume on its own — the voice chat is gone after a
        restart — so the remembered track goes back to the *front* of the
        queue and ``resume_always_on`` decides whether it should start again.
        """
        if not self.storage:
            return 0
        try:
            data = await self.storage.get_meta(_QUEUE_META, {}) or {}
        except Exception as exc:
            logger.debug("could not read the queue snapshot: %s", exc)
            return 0
        if not isinstance(data, dict):
            return 0
        restored = 0
        for raw_id, payload in data.items():
            try:
                chat_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            state = self.queues.get(chat_id)
            state.loop = LoopMode.parse(payload.get("loop") or state.loop.value)
            state.autoplay = bool(payload.get("autoplay", state.autoplay))
            state.shuffle = bool(payload.get("shuffle", state.shuffle))
            state.volume = int(payload.get("volume") or state.volume)
            state.always_on = bool(payload.get("always_on", state.always_on))
            state.effects = audio_fx.resolve(payload.get("effects") or state.effects)
            state.queue = [
                Track.from_dict(item) for item in payload.get("queue") or [] if isinstance(item, dict)
            ]
            current = payload.get("current")
            if isinstance(current, dict):
                track = Track.from_dict(current)
                state.queue.insert(0, track)
                position = float(payload.get("position") or 0.0)
                duration = float(getattr(track, "duration", 0) or 0)
                # Within the last 15 s of a long track, starting over is what
                # people expect; resuming too near the end just skips it.
                limit = max(0.0, duration - 15.0) if duration > 30 else 0.0
                state.offset = max(0.0, min(position, limit))
            state.current = None
            state.playing = False
            state.paused = False
            state.started_at = 0.0
            self._settings_loaded.add(chat_id)
            restored += 1
        if restored:
            journal.info("player", f"restored {restored} queue(s) after a restart")
        return restored

    async def resume_always_on(self) -> int:
        """Start the 24/7 chats again once the voice engine is up."""
        if not self.calls:
            return 0
        started = 0
        for state in self.queues.all():
            if not state.always_on or state.playing or not state.queue:
                continue
            track = self.queues.pop_next_for(state.chat_id)
            if track is None:
                continue
            # Continue where the track had got to before the restart instead of
            # starting a 5-minute song from the beginning.
            resume_at = int(max(0.0, state.offset))
            state.offset = 0.0
            try:
                await self.play_track(
                    state.chat_id,
                    track,
                    video=track.is_video or state.is_video,
                    seek=resume_at,
                )
                started += 1
            except Exception as exc:
                logger.warning("could not resume 24/7 in %s: %s", state.chat_id, exc)
                journal.warn(
                    "player",
                    f"24/7 resume failed in {state.chat_id}",
                    error=str(exc),
                )
        return started

    # ── voice-chat bootstrap ───────────────────────────────────────────────
    async def ensure_voice_chat(self, chat_id: int) -> bool:
        """Open a group call when nobody has started one yet.

        PyTgCalls refuses to join a group without an active call, so a first
        /play in a fresh group used to fail with "start a voice chat first".
        The assistant has the rights to create it, so it does. Returns True
        when a call is available afterwards.
        """
        if not self.assistant:
            return False
        now = time.monotonic()
        if now - self._vc_attempts.get(int(chat_id), 0.0) < 20.0:
            # Do not hammer Telegram when the assistant simply has no rights.
            return False
        self._vc_attempts[int(chat_id)] = now
        try:
            from pyrogram.raw.functions.phone import CreateGroupCall

            peer = await self.assistant.resolve_peer(int(chat_id))
            await self.assistant.invoke(
                CreateGroupCall(peer=peer, random_id=random.randint(10_000, 99_999))
            )
        except Exception as exc:  # already open, no rights, flood wait…
            message = str(exc).lower()
            if "already" in message or "groupcall_already" in message or "already_started" in message:
                return True
            journal.warn(
                "voice",
                f"could not open a voice chat in {chat_id}",
                error=str(exc),
            )
            logger.info("voice chat bootstrap failed in %s: %s", chat_id, exc)
            return False
        logger.info("opened a voice chat in %s", chat_id)
        journal.info("voice", f"opened the voice chat in {chat_id}")
        # Telegram needs a beat before the call accepts a join.
        await asyncio.sleep(1.5)
        return True

    # ── assistant membership ───────────────────────────────────────────────
    async def _assistant_joined(self, chat_id: int) -> bool:
        """Is the streaming account a member of this chat?"""
        from vyron.runtime import runtime as _runtime

        assistant = getattr(_runtime, "assistant", None)
        if assistant is None:
            return False
        try:
            await assistant.get_chat_member(chat_id, "me")
            return True
        except Exception:
            return False

    async def ensure_assistant(self, chat_id: int) -> bool:
        """Invite the assistant into *chat_id* if it is not there yet.

        Ported from ShizuMusic: without this, the first `/play` in an old group
        fails with "the assistant could not join the voice chat" and the person
        has to add the account by hand. A public chat is joined by id; a private
        one needs an invite link, which the *bot* exports (it has the rights
        the assistant does not).
        """
        if await self._assistant_joined(chat_id):
            return True
        from vyron.runtime import runtime as _runtime

        assistant = getattr(_runtime, "assistant", None)
        if assistant is None:
            return False
        try:
            await assistant.join_chat(chat_id)
            logger.info("assistant joined %s", chat_id)
            return True
        except Exception as exc:
            logger.debug("assistant join by id failed in %s: %s", chat_id, exc)
        bot = getattr(_runtime, "bot", None)
        if bot is None:
            return False
        try:
            link = await bot.export_chat_invite_link(chat_id)
            await assistant.join_chat(link)
            logger.info("assistant joined %s via invite link", chat_id)
            return True
        except Exception as exc:
            logger.info("assistant could not join %s: %s", chat_id, exc)
            journal.warn("voice", f"assistant could not join {chat_id}", error=str(exc))
            return False

    # ── streaming primitives ───────────────────────────────────────────────
    async def _start_stream(
        self,
        chat_id: int,
        track: Track,
        *,
        video: bool,
        seek: int = 0,
        count_play: bool = True,
    ) -> None:
        if not self.calls:
            raise StreamError(
                "Voice streaming is not configured — add API_ID, API_HASH and STRING_SESSION."
            )
        state = self.queues.get(chat_id)
        url = ""
        if track.source == "telegram" and _is_local_file(track.url):
            # already downloaded locally — stream the file, not a URL
            url = track.url
        elif track.source in _DIRECT_SOURCES and track.url:
            # A direct stream: the catalogue URL *is* the audio, so ntgcalls can
            # start on the first megabyte instead of waiting for a whole file to
            # be fetched, transcoded and written to disk. Downloading first was
            # the difference between "it plays" and "it plays eight seconds
            # after the card appears".
            url = track.url
        elif (
            getattr(self.settings, "play_from_disk", False)
            and self.downloader is not None
            and not (video is False and self._substitute_first(track))
        ):
            # ShizuMusic's model: fetch the file once, then hand ntgcalls a
            # local path. A local stream cannot 403, expire or be throttled
            # mid-song, which is what makes playback reliable on a datacenter
            # IP — the cache makes the second play of a track instant.
            #
            # Everything *except* a track YouTube is already refusing: there,
            # fetching to disk means "ask a broken engine, then a mirror, then
            # a catalogue, then download the whole song" before the first
            # second of audio. The resolver answers the same question from its
            # own cache, in one step, and ntgcalls streams it straight away.
            try:
                path = await self.downloader.fetch(track, video=video)
                url = str(path)
                logger.info("playing %s from disk (%s)", track.id, Path(path).suffix)
            except Exception as exc:
                logger.warning(
                    "disk playback failed for %s (%s) — falling back to the stream URL",
                    track.id,
                    exc,
                )
                journal.warn("player", "disk playback failed, using the URL", track=track.id, error=str(exc))
        if not url and track.source in _EXTRACT_SOURCES and track.url:
            # SoundCloud / Bandcamp: the page must be extracted before ntgcalls
            # can be handed anything, and it is not a YouTube id. One call, then
            # the song streams — no full download first.
            from vyron.core import extract

            try:
                url = await extract.stream_url(track)
            except Exception as exc:
                logger.warning("extraction failed for %s (%s)", track.id, exc)
                if getattr(self.settings, "play_from_disk", False) and self.downloader is not None:
                    try:
                        url = str(await self.downloader.fetch(track, video=video))
                    except Exception as fallback_exc:
                        logger.warning(
                            "disk fallback failed for %s (%s)", track.id, fallback_exc
                        )
        if not url:
            try:
                info = await self.youtube.stream_info(track, video=video)
            except MediaError as exc:
                # Last resort before telling the chat it failed: the download
                # ladder can still reach a catalogue, and a file on disk plays
                # even when every resolver is having a bad day.
                if self.downloader is not None:
                    try:
                        url = str(await self.downloader.fetch(track, video=video))
                        logger.info("resolved %s from disk after a failed lookup", track.id)
                    except Exception as disk_exc:
                        logger.warning("disk retry failed for %s (%s)", track.id, disk_exc)
                if not url:
                    raise StreamError(f"Could not resolve that track: {exc}") from exc
            else:
                url = info.url
            # The answer can be audio even when video was asked for: a walled
            # YouTube falls back to the same song from a catalogue, and those
            # only carry audio. Asking ntgcalls for a video track that is not
            # in the stream fails the whole play, so the flag follows the
            # bytes and the chat is told the truth instead.
            if video and not _is_video_stream(info):
                video = False
                state.is_video = False
                logger.info("playing %s as audio (no video available)", track.id)
                journal.warn(
                    "player",
                    "no video for this one — streaming the same song as audio",
                    track=track.id,
                    source=info.source or "youtube",
                )

        stream = MediaStream(
            url,
            audio_parameters=_audio_quality(self.settings.audio_quality),
            video_parameters=_video_quality(self.settings.video_quality),
            ffmpeg_parameters=audio_fx.ffmpeg_parameters(
                state.effects, seek=seek
            ),
            video_flags=(MediaStream.Flags.REQUIRED if video else MediaStream.Flags.IGNORE),
        )
        try:
            try:
                await self.calls.play(
                    chat_id,
                    stream,
                    config=GroupCallConfig(auto_start=True),
                )
            except NoActiveGroupCall:
                if not await self.ensure_voice_chat(chat_id):
                    raise StreamError(
                        "There is no voice chat here, and I could not open one — "
                        "give the assistant permission to manage voice chats."
                    ) from None
                await self.calls.play(
                    chat_id,
                    stream,
                    config=GroupCallConfig(auto_start=True),
                )
        except NotInCallError as exc:
            # The assistant is not in the chat: invite it, then try once more.
            if await self.ensure_assistant(chat_id):
                try:
                    await self.calls.play(
                        chat_id,
                        stream,
                        config=GroupCallConfig(auto_start=True),
                    )
                    self._in_call.add(int(chat_id))
                    return
                except Exception as retry_exc:
                    logger.info("retry after joining failed in %s: %s", chat_id, retry_exc)
                    raise StreamError(
                        f"Playback failed: {retry_exc}"
                    ) from None
            raise StreamError("The assistant could not join the voice chat.") from exc
        except NoActiveGroupCall as exc:
            raise StreamError("Start a voice chat in this group first, then try again.") from exc
        except Exception as exc:
            # A missing assistant usually surfaces as a channel/peer error, so
            # try the invite path once before giving up.
            if await self.ensure_assistant(chat_id):
                try:
                    await self.calls.play(
                        chat_id,
                        stream,
                        config=GroupCallConfig(auto_start=True),
                    )
                    self._in_call.add(int(chat_id))
                    return
                except Exception:
                    pass
            logger.warning("stream start failed in %s: %s", chat_id, exc)
            journal.error("player", f"stream start failed in {chat_id}", exc, track=track.id)
            raise StreamError(f"Playback failed: {exc}") from exc

        self._in_call.add(int(chat_id))
        journal.ok(
            "player",
            f"streaming “{track.title}”",
            chat=chat_id,
            track=track.id,
            video=video,
            seek=seek,
            source=track.source,
        )
        state.current = track
        state.playing = True
        state.paused = False
        state.is_video = video
        state.started_at = clock()
        state.offset = float(seek)
        state.paused_at = None
        state.touch()
        self.tracks_played += 1

        try:
            await self.calls.change_volume_call(chat_id, state.volume)
        except Exception:
            pass

        state.prefetched = None
        if count_play and self.storage:
            try:
                await self.storage.bump("tracks")
                if track.requested_by:
                    await self.storage.add_history(track.requested_by, track.to_dict())
            except Exception as exc:
                logger.debug("history write failed: %s", exc)

    @staticmethod
    def _substitute_first(track: Track) -> bool:
        """True when YouTube is refusing this host and *track* is a YouTube one.

        A walled YouTube track cannot play from here at all; the audio comes
        from a catalogue. Asking the resolver for it is one cached step, while
        downloading it to disk re-walks the whole ladder first.
        """
        source = str(getattr(track, "source", "") or "").lower()
        if source not in {"youtube", "ytmusic", "youtube_music", ""}:
            return False
        try:
            from vyron.runtime import runtime

            engine = getattr(runtime, "youtube", None)
            return bool(engine is not None and engine.walled())
        except Exception:  # pragma: no cover - before runtime exists
            return False

    @staticmethod
    def _may_stream() -> bool:
        """False on a standby instance — a voice chat gets one streamer.

        Two copies of the bot joined to the same call do not take turns; they
        interrupt each other. Refusing here is the difference between a degraded
        deployment and a broken one.
        """
        try:
            from vyron.runtime import runtime

            return runtime.primary
        except Exception:  # pragma: no cover - before runtime exists
            return True

    async def play_track(
        self,
        chat_id: int,
        track: Track,
        *,
        video: bool = False,
        seek: int = 0,
        announce: bool = True,
        count_play: bool = True,
    ) -> None:
        """Start *track* now.

        ``announce=False`` updates the existing now-playing message instead of
        posting a new one, and ``count_play=False`` leaves the stats and the
        history alone — both matter when a seek restarts the same stream.
        """
        if not self._may_stream():
            raise StreamError(
                "This instance is a standby — another copy of the bot owns the "
                "voice chat. Scale the service to one instance."
            )
        async with self.lock(chat_id):
            await self._start_stream(
                chat_id, track, video=video, seek=seek, count_play=count_play
            )
            if announce:
                await self._send_now_playing(chat_id)
            else:
                await self.refresh_now_playing(chat_id, force=True)
        self._schedule_prefetch(chat_id)
        self.schedule_save()

    async def enqueue(
        self,
        chat_id: int,
        track: Track,
        *,
        video: bool = False,
        play_now: bool = False,
        index: int | None = None,
    ) -> int:
        """Queue *track* — or start it when the player is idle.

        Returns the 1-based queue position (1 = started immediately,
        -1 = duplicate, 0 = queue full).  Existing playback is never
        interrupted; use :meth:`jump` for that.

        A chat can hold a *stale* current track: the stream died, the assistant
        was kicked, the process restarted mid-song. ``playing`` is the truth,
        so a stale ``current`` no longer blocks the next /play — which used to
        queue a track behind a ghost and never play it.
        """
        state = await self.restore_settings(chat_id)
        if not state.playing:
            # Nothing is actually streaming: clean the ghost and start now.
            state.current = None
            state.reset_stream()
            await self.play_track(chat_id, track, video=video)
            return 1
        position = self.queues.add(
            chat_id,
            track,
            index=index,
            max_size=self.settings.max_queue_size,
        )
        if position > 0:
            self.schedule_save()
        return position

    # ── transport ──────────────────────────────────────────────────────────
    async def pause(self, chat_id: int) -> bool:
        state = self.queues.get(chat_id)
        if not state.playing or state.paused or not self.calls:
            return False
        try:
            await self.calls.pause(chat_id)
        except Exception as exc:
            logger.debug("pause failed: %s", exc)
            return False
        state.offset = state.elapsed()
        state.paused = True
        state.paused_at = clock()
        state.touch()
        await self.refresh_now_playing(chat_id)
        return True

    async def resume(self, chat_id: int) -> bool:
        state = self.queues.get(chat_id)
        if not state.playing or not state.paused or not self.calls:
            return False
        try:
            await self.calls.resume(chat_id)
        except Exception as exc:
            logger.debug("resume failed: %s", exc)
            return False
        state.started_at = clock()
        state.paused = False
        state.paused_at = None
        state.touch()
        await self.refresh_now_playing(chat_id)
        return True

    async def toggle(self, chat_id: int) -> bool | None:
        state = self.queues.get(chat_id)
        if not state.playing:
            return None
        return await self.resume(chat_id) if state.paused else await self.pause(chat_id)

    async def seek(self, chat_id: int, seconds: int) -> bool:
        state = self.queues.get(chat_id)
        if not state.current:
            return False
        total = state.current.duration or 0
        target = max(0, int(seconds))
        if total:
            target = min(total - 1, target)
        # Restarting the same stream must not post a second now-playing card,
        # bump the play counter or write history: it is still one play.
        await self.play_track(
            chat_id,
            state.current,
            video=state.is_video,
            seek=target,
            announce=False,
            count_play=False,
        )
        return True

    async def set_volume(self, chat_id: int, volume: int) -> int:
        state = self.queues.get(chat_id)
        state.volume = max(1, min(200, int(volume)))
        state.touch()
        if self.calls and int(chat_id) in self._in_call:
            try:
                await self.calls.change_volume_call(chat_id, state.volume)
            except Exception as exc:
                logger.debug("volume change failed: %s", exc)
        await self.persist(chat_id)
        await self.refresh_now_playing(chat_id)
        return state.volume

    # ── advancing ──────────────────────────────────────────────────────────
    async def skip(self, chat_id: int, *, count: int = 1, natural: bool = False) -> Track | None:
        state = self.queues.get(chat_id)
        if not state.current and not state.queue:
            return None

        async with self.lock(chat_id):
            if not natural:
                for _ in range(max(0, count - 1)):
                    self.queues.pop_next_for(chat_id)

            if natural and state.loop is LoopMode.ONE and state.current:
                await self._start_stream(
                    chat_id, state.current, video=state.is_video, count_play=False
                )
                await self._send_now_playing(chat_id, edit=True)
                self._schedule_prefetch(chat_id)
                return state.current

            if natural and state.loop is LoopMode.ALL and state.current:
                self.queues.rotate_current_to_end(chat_id)

            if state.current:
                state.history.append(state.current)
                del state.history[:-25]

            # A dead link should cost one track, not the whole session: walk
            # the queue until something actually starts.
            attempts = max(1, len(state.queue) + 1)
            next_track = self.queues.pop_next_for(chat_id)
            for attempt in range(attempts):
                if next_track is None and attempt == 0:
                    next_track = await self._autoplay_track(chat_id, state)
                if next_track is None:
                    break
                try:
                    await self._start_stream(
                        chat_id,
                        next_track,
                        video=next_track.is_video or state.is_video,
                    )
                except StreamError as exc:
                    journal.warn(
                        "player",
                        f"skipped “{next_track.title}” — could not stream it",
                        error=str(exc),
                        track=next_track.id,
                    )
                    logger.warning("could not start %s in %s: %s", next_track.id, chat_id, exc)
                    next_track = self.queues.pop_next_for(chat_id)
                    continue
                await self._send_now_playing(chat_id)
                self._schedule_prefetch(chat_id)
                return next_track

        self.schedule_save()
        await self.stop(chat_id, leave=not state.always_on, announce=natural)
        return None

    async def _autoplay_track(self, chat_id: int, state: ChatState) -> Track | None:
        if not state.autoplay or not state.current:
            return None
        if state.prefetched is not None and state.prefetched not in state.history:
            track, state.prefetched = state.prefetched, None
            track.requested_name = "autoplay"
            return track
        # Mood/language-aware first (autoplay.py), related-videos second: a
        # chat that asked for Malayalam should not fall out of the lane just
        # because YouTube's related graph suggested a gaming montage.
        from vyron.core import autoplay as auto

        # What was played *twice in a row* is what makes autoplay feel broken,
        # so the artist streak travels with the request.
        streak = [
            getattr(item, "uploader", "") or ""
            for item in state.history[-2:]
            if item is not None
        ]
        try:
            chosen = await auto.next_track(
                self.youtube,
                state.current,
                mood=state.mood,
                language=state.language,
                played=state.history,
                streak_artists=streak,
            )
            if chosen is not None:
                return chosen
        except Exception as exc:  # pragma: no cover - autoplay must never break
            logger.debug("autoplay lane failed: %s", exc)

        try:
            suggestions = await self.youtube.related(state.current, limit=5)
        except Exception as exc:
            logger.debug("autoplay lookup failed: %s", exc)
            return None
        for candidate in suggestions:
            if candidate not in state.history:
                candidate.requested_name = "autoplay"
                return candidate
        return None

    async def jump(self, chat_id: int, position: int) -> Track | None:
        state = self.queues.get(chat_id)
        if position < 1 or position > len(state.queue):
            return None
        track = self.queues.remove(chat_id, position)
        if not track:
            return None
        if state.current:
            state.history.append(state.current)
            del state.history[:-25]
        await self.play_track(chat_id, track, video=track.is_video or state.is_video)
        return track

    async def stop(self, chat_id: int, *, leave: bool = True, announce: bool = False) -> None:
        state = self.queues.get(chat_id)
        journal.info("player", f"playback stopped in {chat_id}", leave=leave, queued=len(state.queue))
        state.reset_stream()
        state.current = None
        state.queue.clear()
        state.touch()
        state.prefetched = None
        self._cancel_np(chat_id)
        self._cancel_prefetch(chat_id)
        self.schedule_save()
        if leave:
            await self.leave(chat_id)
        if announce and self.bot:
            try:
                await rich.send(
                    self.bot,
                    chat_id,
                    cards.warn_card("<b>Queue finished</b> — add more with /play."),
                )
            except Exception:
                pass

    async def leave(self, chat_id: int) -> bool:
        state = self.queues.get(chat_id)
        state.reset_stream()
        state.prefetched = None
        self._in_call.discard(int(chat_id))
        self._cancel_np(chat_id)
        self._cancel_prefetch(chat_id)
        if not self.calls:
            return False
        try:
            await self.calls.leave_call(chat_id)
            journal.info("voice", f"left voice chat {chat_id}")
            return True
        except Exception as exc:
            logger.debug("leave failed: %s", exc)
            journal.warn("voice", f"could not leave voice chat {chat_id}", error=str(exc))
            return False

    # ── now playing card ───────────────────────────────────────────────────
    async def _send_now_playing(self, chat_id: int, *, edit: bool = False) -> None:
        if not self.bot:
            return
        state = self.queues.get(chat_id)
        if not state.current:
            return
        await nowplaying.announce(self.bot, chat_id, state, edit=edit)
        if state.np_message_id and state.playing:
            self._start_np_loop(chat_id)

    async def refresh_now_playing(self, chat_id: int, *, force: bool = False) -> None:
        state = self.queues.get(chat_id)
        if not self.bot or not state.current or not state.np_message_id:
            return
        if not force and not state.playing:
            return
        from vyron.core import i18n

        markup = (
            cards.now_playing_caption(state, await i18n.for_chat(chat_id))
            if rich.is_photo(chat_id, state.np_message_id)
            else cards.now_playing_card(state)
        )
        await rich.edit(
            self.bot,
            chat_id,
            state.np_message_id,
            markup,
            markup_keyboard=keyboards.now_playing(state),
        )

    # ── prefetch ───────────────────────────────────────────────────────────
    def _schedule_prefetch(self, chat_id: int) -> None:
        """Warm the next track (or the next suggestion) while this one plays.

        Resolving a stream is a couple of seconds of yt-dlp work; doing it in
        the gap after a track ends is audible dead air. Queue lookups are also
        cached in the YouTube client, so this makes the hand-off seamless.
        """
        task = self._prefetch_tasks.get(int(chat_id))
        if task and not task.done():
            return
        try:
            self._prefetch_tasks[int(chat_id)] = asyncio.create_task(
                self._prefetch_worker(int(chat_id))
            )
        except RuntimeError:  # pragma: no cover - no running loop (tests)
            pass

    def _cancel_prefetch(self, chat_id: int) -> None:
        task = self._prefetch_tasks.pop(int(chat_id), None)
        if task and not task.done():
            task.cancel()

    async def _prefetch_worker(self, chat_id: int) -> None:
        """Warm what plays next — a bounded number, inside a time budget.

        The next two tracks matter: after a skip or a finished song the hand-off
        is audible dead air. But every warm-up is a yt-dlp run, so the pass has
        a wall-clock deadline and never starts while nothing is playing or the
        chat is paused — a background task competing with the song on air is
        worse than the dead air it prevents.
        """
        started = time.monotonic()
        depth = max(0, int(getattr(self.settings, "preheat_depth", 2)))
        budget = max(0.0, float(getattr(self.settings, "preheat_seconds", 25)))
        if depth == 0:
            return
        try:
            state = self.queues.get(chat_id)
            if not state.playing or state.paused:
                return
            warmed = 0
            for upcoming in list(state.queue)[:depth]:
                if time.monotonic() - started > budget:
                    logger.debug("preheat budget spent in %s after %d track(s)", chat_id, warmed)
                    break
                await self.youtube.stream_info(upcoming, video=upcoming.is_video)
                warmed += 1
            if warmed:
                return
            if not state.autoplay or not state.current:
                return
            for candidate in await self.youtube.related(state.current, limit=3):
                if candidate not in state.history and candidate != state.current:
                    state.prefetched = candidate
                    await self.youtube.stream_info(candidate, video=candidate.is_video)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # prefetch is an optimisation, never a failure
            logger.debug("prefetch for %s skipped: %s", chat_id, exc)

    def _start_np_loop(self, chat_id: int) -> None:
        task = self._np_tasks.get(int(chat_id))
        if task and not task.done():
            return
        self._np_tasks[int(chat_id)] = asyncio.create_task(self._np_worker(chat_id))

    def _cancel_np(self, chat_id: int) -> None:
        task = self._np_tasks.pop(int(chat_id), None)
        if task and not task.done():
            task.cancel()

    async def _np_worker(self, chat_id: int) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.np_refresh_seconds)
                state = self.queues.get(chat_id)
                if not state.playing or not state.current:
                    break
                if state.paused:
                    continue
                await self.refresh_now_playing(chat_id, force=True)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("np worker stopped: %s", exc)

    # ── pytgcalls update handlers ──────────────────────────────────────────
    def register_handlers(self) -> None:
        """Wire the voice-chat events into the player.

        Every registration is isolated: pytgcalls' filter constructors are
        version-specific (`chat_update` needs a ``ChatUpdate.Status`` mask since
        2.2), and a mismatch there must never abort the whole boot — the bot can
        keep serving search, cards and downloads without live events.
        """
        if not self.calls:
            return

        def _wire(factory, handler, label: str) -> None:
            try:
                self.calls.on_update(factory())(handler)
            except Exception as exc:
                logger.error(
                    "could not register the %s handler (%s: %s) — live updates for it are off",
                    label,
                    type(exc).__name__,
                    exc,
                )

        async def _on_stream_end(client, update):  # noqa: ANN001
            await self.on_stream_end(client, update)

        async def _on_chat_update(client, update):  # noqa: ANN001
            await self.on_chat_update(client, update)

        _wire(lambda: fl.stream_end(), _on_stream_end, "stream-end")
        _wire(self._chat_update_filter, _on_chat_update, "chat-update")

    @staticmethod
    def _chat_update_filter():
        """The filter for "the call is over", across pytgcalls versions."""
        from pytgcalls.types import ChatUpdate

        flags = None
        for name in ("KICKED", "CLOSED_VOICE_CHAT", "LEFT_GROUP", "DISCARDED_CALL"):
            member = getattr(ChatUpdate.Status, name, None)
            if member is None:
                continue
            flags = member if flags is None else flags | member
        if flags is None:  # pragma: no cover - very old pytgcalls
            raise RuntimeError("no ChatUpdate.Status flags available")
        return fl.chat_update(flags)

    @staticmethod
    def duplicate_stream_end(state: ChatState, now: float) -> bool:
        """True when this stream-end is a repeat for the same track.

        A video track reports both an audio and a video stream end; without this
        the second event used to skip the track that had just started.
        """
        if not state.current:
            return True
        key = f"{state.current.id}:{'v' if state.is_video else 'a'}"
        if state.ended_track == key and now - state.ended_at < 3.0:
            return True
        state.ended_track = key
        state.ended_at = now
        return False

    async def _recover_stream(self, chat_id: int, state, played: float) -> bool:
        """A stream died mid-song — pick the song up where it stopped.

        YouTube URLs expire, a datacenter IP gets throttled, a direct host
        hiccups. None of that should skip to the next track: the listener is
        two minutes into a four-minute song, so the right answer is to resolve
        the same song somewhere else and resume with a small rewind.
        """
        now = clock()
        if now - self._recovered_at.get(chat_id, 0.0) < 25.0:
            return False            # one attempt per track, not a retry storm
        current = state.current
        if current is None:
            return False
        self._recovered_at[chat_id] = now
        seek = max(0, int(played) - 3)
        query = f"{current.title} {current.uploader or ''}".strip()

        candidates: list[Track] = []
        try:
            from vyron.core import sources as source_registry

            candidates.extend(
                await source_registry.fallback_search(query, 2, settings=self.settings)
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("recovery search failed: %s", exc)
        try:
            found = await self.youtube.search(query, limit=1)
            candidates.extend(found)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("recovery youtube search failed: %s", exc)

        seen: set[str] = {current.id}
        for candidate in candidates:
            key = f"{candidate.source}:{candidate.id}"
            if candidate.id in seen:
                continue
            seen.add(candidate.id)
            try:
                await self.play_track(
                    chat_id,
                    candidate,
                    video=candidate.is_video or state.is_video,
                    seek=seek,
                    announce=False,
                    count_play=False,
                )
            except StreamError as exc:
                logger.info("recovery via %s failed: %s", key, exc)
                continue
            logger.info(
                "recovered “%s” in %s at %ss via %s", current.title, chat_id, seek, candidate.source
            )
            journal.warn(
                "player",
                f"stream dropped — resumed “{current.title}” at {seek}s from {candidate.source}",
                chat=chat_id,
                track=current.id,
                elapsed=round(played, 1),
                source=candidate.source,
            )
            return True
        journal.error("player", f"could not recover “{current.title}”", chat=chat_id, track=current.id)
        return False

    async def on_stream_end(self, _client, update) -> None:
        chat_id = int(getattr(update, "chat_id", 0) or 0)
        if not chat_id:
            return
        state = self.queues.get(chat_id)
        if not state.current:
            return
        stream_type = str(getattr(update, "stream_type", "") or "")
        if "VIDEO" in stream_type.upper() and not state.is_video:
            return
        if self.duplicate_stream_end(state, clock()):
            logger.debug("ignoring duplicate stream end in %s", chat_id)
            return

        # A stream that ends early is a drop, not a finished song. Check before
        # treating it as "next track", otherwise a 403 at 0:40 looks exactly
        # like a track that simply ended.
        track = state.current
        played = state.elapsed(clock())
        duration = int(getattr(track, "duration", 0) or 0)
        unfinished = duration > 30 and played < duration - 5
        if unfinished and not state.paused and played >= 5:
            if await self._recover_stream(chat_id, state, played):
                return
        try:
            await self.skip(chat_id, natural=True)
        except Exception as exc:
            logger.warning("auto-advance failed in %s: %s", chat_id, exc)

    async def on_chat_update(self, _client, update) -> None:
        chat_id = int(getattr(update, "chat_id", 0) or 0)
        raw_status = getattr(update, "status", "") or ""
        # pytgcalls 2.x hands over a Status flag, older builds a string.
        status = getattr(raw_status, "name", None) or str(raw_status)
        status = str(status).upper()
        if not chat_id:
            return
        if any(word in status for word in ("KICKED", "CLOSED", "LEFT", "DISCARDED")):
            logger.info("assistant removed from %s (%s)", chat_id, status)
            state = self.queues.get(chat_id)
            was_streaming = bool(state.current or state.playing)
            state.reset_stream()
            state.current = None
            state.queue.clear()
            state.prefetched = None
            self._in_call.discard(chat_id)
            self._cancel_np(chat_id)
            self._cancel_prefetch(chat_id)
            self.schedule_save()
            journal.warn("voice", f"voice chat ended externally in {chat_id}", status=status)
            # Tell the chat instead of going quiet: a stream that dies from
            # outside used to look like the bot had simply stopped working.
            if was_streaming and self.bot:
                try:
                    await rich.send(
                        self.bot,
                        chat_id,
                        cards.warn_card(
                            "<b>Voice chat ended</b>\n"
                            "<blockquote>The call was closed outside the bot, so playback "
                            "stopped. Start a voice chat and send /play again.</blockquote>"
                        ),
                    )
                except Exception:
                    pass

    # ── background tasks ───────────────────────────────────────────────────
    async def start_background(self) -> None:
        self._running = True
        self._idle_task = asyncio.create_task(self._idle_worker())
        self._empty_task = asyncio.create_task(self._empty_vc_worker())

    async def shutdown(self) -> None:
        self._running = False
        for task in (getattr(self, "_idle_task", None), getattr(self, "_empty_task", None)):
            if task and not task.done():
                task.cancel()
        for task in list(self._np_tasks.values()):
            if not task.done():
                task.cancel()
        for task in list(self._prefetch_tasks.values()):
            if not task.done():
                task.cancel()

    async def _vc_is_empty(self, chat_id: int) -> bool:
        """True when the assistant is alone in the voice chat."""
        if not self.calls:
            return False
        try:
            participants = await self.calls.get_participants(chat_id)
        except Exception:
            return False
        if participants is None:
            return False
        humans = [p for p in participants if int(getattr(p, "user_id", 0) or 0) != 0]
        return len(humans) <= 1

    async def _empty_vc_worker(self) -> None:
        """Leave voice chats nobody is listening to."""
        await asyncio.sleep(45)
        while self._running:
            try:
                for chat_id in list(self._in_call):
                    state = self.queues.get(chat_id)
                    if state.always_on or not state.playing:
                        self._empty_checks.pop(chat_id, None)
                        continue
                    if await self._vc_is_empty(chat_id):
                        checks = self._empty_checks.get(chat_id, 0) + 1
                        self._empty_checks[chat_id] = checks
                        if checks >= 3:  # ~3 minutes of silence
                            logger.info("leaving empty voice chat %s", chat_id)
                            await self.stop(chat_id, leave=True)
                            self._empty_checks.pop(chat_id, None)
                    else:
                        self._empty_checks.pop(chat_id, None)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("empty-vc worker error: %s", exc)
            await asyncio.sleep(60)

    async def _idle_worker(self) -> None:
        interval = 20
        while self._running:
            try:
                await asyncio.sleep(interval)
                for chat_id in list(self._in_call):
                    state = self.queues.get(chat_id)
                    if state.playing or state.always_on or state.queue:
                        continue
                    if time.monotonic() - state.last_activity < self.settings.idle_leave_seconds:
                        continue
                    await self.leave(chat_id)
                    logger.info("left idle voice chat %s", chat_id)
                    if self.bot and state.np_message_id:
                        await rich.edit(
                            self.bot,
                            chat_id,
                            state.np_message_id,
                            cards.warn_card(
                                f"<b>Left the voice chat</b> after "
                                f"{int(self.settings.idle_leave_seconds / 60)} min of silence."
                            ),
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("idle worker error: %s", exc)


__all__ = ["Player", "StreamError"]
