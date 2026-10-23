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
from vyron.core.search import MediaError, YouTube
from vyron.database import Storage
from vyron.ui import cards, keyboards
from vyron.ui import rich
from vyron.ui.progress import now as clock

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.bot = bot
        self.calls = calls
        self.settings = settings
        self.storage = storage
        self.youtube = youtube
        self.queues = QueueManager(settings.default_volume, settings.autoplay_default)

        self._locks: dict[int, asyncio.Lock] = {}
        self._np_tasks: dict[int, asyncio.Task] = {}
        self._in_call: set[int] = set()
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
        data = await self.storage.chat_settings(chat_id)
        if data:
            state.loop = LoopMode.parse(data.get("loop", state.loop.value))
            state.autoplay = bool(data.get("autoplay", state.autoplay))
            state.volume = int(data.get("volume", state.volume) or state.volume)
            state.always_on = bool(data.get("always_on", state.always_on))
            state.effects = audio_fx.resolve(data.get("effects", []))
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
            },
        )

    # ── streaming primitives ───────────────────────────────────────────────
    async def _start_stream(self, chat_id: int, track: Track, *, video: bool, seek: int = 0) -> None:
        if not self.calls:
            raise StreamError(
                "Voice streaming is not configured — add API_ID, API_HASH and STRING_SESSION."
            )
        state = self.queues.get(chat_id)
        try:
            if track.source == "telegram" and Path(track.url).is_file():
                # already downloaded locally — stream the file, not a URL
                url = track.url
            else:
                url = await self.youtube.stream_url(track, video=video)
        except MediaError as exc:
            raise StreamError(f"Could not resolve that track: {exc}") from exc

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
            await self.calls.play(
                chat_id,
                stream,
                config=GroupCallConfig(auto_start=True),
            )
        except NoActiveGroupCall as exc:
            raise StreamError("Start a voice chat in this group first, then try again.") from exc
        except NotInCallError as exc:
            raise StreamError("The assistant could not join the voice chat.") from exc
        except Exception as exc:
            logger.warning("stream start failed in %s: %s", chat_id, exc)
            raise StreamError(f"Playback failed: {exc}") from exc

        self._in_call.add(int(chat_id))
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

        if self.storage:
            try:
                await self.storage.bump("tracks")
                if track.requested_by:
                    await self.storage.add_history(track.requested_by, track.to_dict())
            except Exception as exc:
                logger.debug("history write failed: %s", exc)

    async def play_track(self, chat_id: int, track: Track, *, video: bool = False, seek: int = 0) -> None:
        async with self.lock(chat_id):
            await self._start_stream(chat_id, track, video=video, seek=seek)
            await self._send_now_playing(chat_id)

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
        """
        state = await self.restore_settings(chat_id)
        idle = not state.playing and state.current is None
        if idle:
            await self.play_track(chat_id, track, video=video)
            return 1
        position = self.queues.add(
            chat_id,
            track,
            index=index,
            max_size=self.settings.max_queue_size,
        )
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
        await self.play_track(chat_id, state.current, video=state.is_video, seek=target)
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

        if not natural:
            for _ in range(max(0, count - 1)):
                self.queues.pop_next_for(chat_id)

        if natural and state.loop is LoopMode.ONE and state.current:
            await self.play_track(chat_id, state.current, video=state.is_video)
            return state.current

        if natural and state.loop is LoopMode.ALL and state.current:
            self.queues.rotate_current_to_end(chat_id)

        if state.current:
            state.history.append(state.current)
            del state.history[:-25]

        next_track = self.queues.pop_next_for(chat_id)
        if next_track is None:
            next_track = await self._autoplay_track(chat_id, state)
        if next_track is None:
            await self.stop(chat_id, leave=not state.always_on, announce=natural)
            return None

        await self.play_track(chat_id, next_track, video=next_track.is_video or state.is_video)
        return next_track

    async def _autoplay_track(self, chat_id: int, state: ChatState) -> Track | None:
        if not state.autoplay or not state.current:
            return None
        try:
            suggestions = await self.youtube.related(state.current, limit=3)
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
        state.reset_stream()
        state.current = None
        state.queue.clear()
        state.touch()
        self._cancel_np(chat_id)
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
        self._in_call.discard(int(chat_id))
        self._cancel_np(chat_id)
        if not self.calls:
            return False
        try:
            await self.calls.leave_call(chat_id)
            return True
        except Exception as exc:
            logger.debug("leave failed: %s", exc)
            return False

    # ── now playing card ───────────────────────────────────────────────────
    async def _send_now_playing(self, chat_id: int, *, edit: bool = False) -> None:
        if not self.bot:
            return
        state = self.queues.get(chat_id)
        if not state.current:
            return
        markup = cards.now_playing_card(state)
        keyboard = keyboards.now_playing(state)
        if edit and state.np_message_id:
            if await rich.edit(self.bot, chat_id, state.np_message_id, markup, markup_keyboard=keyboard):
                return
        message = await rich.send(self.bot, chat_id, markup, markup_keyboard=keyboard, editable=True)
        if message:
            state.np_message_id = message.id
            self._start_np_loop(chat_id)

    async def refresh_now_playing(self, chat_id: int, *, force: bool = False) -> None:
        state = self.queues.get(chat_id)
        if not self.bot or not state.current or not state.np_message_id:
            return
        if not force and not state.playing:
            return
        await rich.edit(
            self.bot,
            chat_id,
            state.np_message_id,
            cards.now_playing_card(state),
            markup_keyboard=keyboards.now_playing(state),
        )

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
        if not self.calls:
            return

        def _make(filter_obj):
            return filter_obj() if isinstance(filter_obj, type) else filter_obj

        @self.calls.on_update(_make(fl.stream_end))
        async def _on_stream_end(client, update):  # noqa: ANN001
            await self.on_stream_end(client, update)

        @self.calls.on_update(_make(fl.chat_update))
        async def _on_chat_update(client, update):  # noqa: ANN001
            await self.on_chat_update(client, update)

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
        try:
            await self.skip(chat_id, natural=True)
        except Exception as exc:
            logger.warning("auto-advance failed in %s: %s", chat_id, exc)

    async def on_chat_update(self, _client, update) -> None:
        chat_id = int(getattr(update, "chat_id", 0) or 0)
        status = str(getattr(update, "status", "") or "").upper()
        if not chat_id:
            return
        if any(word in status for word in ("KICKED", "CLOSED", "LEFT", "DISCARDED")):
            logger.info("assistant removed from %s (%s)", chat_id, status)
            self.queues.get(chat_id).reset_stream()
            self.queues.get(chat_id).current = None
            self.queues.get(chat_id).queue.clear()
            self._in_call.discard(chat_id)
            self._cancel_np(chat_id)

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
