"""Per-group serialized players and persistent queues."""
import asyncio
import logging
from collections import defaultdict

from sqlalchemy import delete, func, select
from pytgcalls.types import AudioQuality, MediaStream, VideoQuality

from .assistants import NoAssistant
from .db import Favorite, Group, History, QueueTrack, ensure_group
from .sources import SourceError, Track

log = logging.getLogger(__name__)


class PlayerError(Exception):
    pass


class PlayerManager:
    def __init__(self, db, source, pool, max_queue=100):
        self.db, self.source, self.pool = db, source, pool
        self.max_queue = max_queue
        self.locks = defaultdict(asyncio.Lock)
        self.active = {}  # chat -> reserved assistant; never shared playback state
        self.generations = defaultdict(int)
        self.closed = False

    async def queue(self, chat_id):
        async with self.db.sessions() as session:
            rows = (await session.scalars(select(QueueTrack).where(QueueTrack.chat_id == chat_id).order_by(QueueTrack.position))).all()
            return [Track(r.source_id, r.title, r.duration, r.thumbnail, r.video) for r in rows]

    async def enqueue(self, chat_id, track):
        async with self.locks[chat_id]:
            if self.closed:
                raise PlayerError('The player is shutting down.')
            async with self.db.sessions() as session, session.begin():
                await ensure_group(session, chat_id)
                count = await session.scalar(select(func.count()).select_from(QueueTrack).where(QueueTrack.chat_id == chat_id))
                if count >= self.max_queue:
                    raise PlayerError('The queue is full.')
                position = await session.scalar(select(func.max(QueueTrack.position)).where(QueueTrack.chat_id == chat_id))
                session.add(QueueTrack(chat_id=chat_id, position=(position or 0) + 1, source_id=track.source_id,
                                       title=track.title, duration=track.duration, thumbnail=track.thumbnail, video=track.video))
            if chat_id not in self.active:
                await self._start(chat_id)
            return count + 1

    async def _start(self, chat_id, exclude=None):
        tracks = await self.queue(chat_id)
        if not tracks:
            await self._leave(chat_id)
            return
        track = tracks[0]
        # Extract once per start/recovery, not when adding to the queue.
        media, audio, headers = await self.source.resolve(track)
        failed = set(exclude or ())
        while True:
            try:
                assistant = await self.pool.acquire(chat_id, failed)
            except NoAssistant as exc:
                raise PlayerError(str(exc)) from exc
            try:
                # MediaStream is mutated by PyTgCalls during preparation; create one per attempt.
                stream = MediaStream(media, audio_path=audio, headers=headers, audio_parameters=AudioQuality.HIGH,
                                     video_parameters=VideoQuality.HD_720p,
                                     audio_flags=MediaStream.Flags.REQUIRED,
                                     video_flags=MediaStream.Flags.REQUIRED if track.video else MediaStream.Flags.IGNORE)
                await asyncio.wait_for(assistant.calls.play(chat_id, stream), timeout=45)
                self.active[chat_id] = assistant
                self.generations[chat_id] += 1
                async with self.db.sessions() as session, session.begin():
                    group = await session.get(Group, chat_id)
                    volume = group.volume
                    session.add(History(chat_id=chat_id, source_id=track.source_id, title=track.title))
                if volume != 100:
                    try:
                        await assistant.calls.change_volume_call(chat_id, volume)
                    except Exception as exc:
                        log.warning('Could not restore group volume (%s)', type(exc).__name__)
                return
            except Exception as exc:
                log.warning('Assistant %s could not start in group %s (%s)', assistant.name, chat_id, type(exc).__name__)
                if self.active.get(chat_id) is assistant:
                    self.active.pop(chat_id, None)
                    self.generations[chat_id] += 1
                failed.add(assistant.name)
                try:
                    await assistant.calls.leave_call(chat_id)
                except Exception as cleanup_error:
                    log.warning('Assistant cleanup failed (%s)', type(cleanup_error).__name__)
                await self.pool.release(chat_id)
                if len(failed) >= len(self.pool.assistants):
                    raise PlayerError('Could not start playback. Check the voice chat and assistant access.') from exc

    async def _leave(self, chat_id):
        assistant = self.active.pop(chat_id, None)
        if assistant:
            try:
                await assistant.calls.leave_call(chat_id)
            except Exception as exc:
                log.warning('Failed to leave voice chat %s (%s)', chat_id, type(exc).__name__)
        await self.pool.release(chat_id)

    async def advance(self, chat_id, repeat=False, expected_generation=None):
        async with self.locks[chat_id]:
            if expected_generation is not None and self.generations[chat_id] != expected_generation:
                return
            if chat_id not in self.active:
                raise PlayerError('Nothing is playing.')
            async with self.db.sessions() as session, session.begin():
                first = await session.scalar(select(QueueTrack).where(QueueTrack.chat_id == chat_id).order_by(QueueTrack.position).limit(1))
                group = await session.get(Group, chat_id)
                if first and not (repeat and group.loop):
                    await session.delete(first)
            if await self.queue(chat_id):
                try:
                    await self._start(chat_id)
                except (SourceError, PlayerError):
                    await self._leave(chat_id)
                    raise
            else:
                await self._leave(chat_id)

    async def retry(self, chat_id):
        async with self.locks[chat_id]:
            if not await self.queue(chat_id):
                raise PlayerError('The queue is empty.')
            await self._leave(chat_id)
            await self._start(chat_id)

    async def stop(self, chat_id):
        async with self.locks[chat_id]:
            async with self.db.sessions() as session, session.begin():
                await session.execute(delete(QueueTrack).where(QueueTrack.chat_id == chat_id))
            await self._leave(chat_id)

    async def clear(self, chat_id):
        async with self.locks[chat_id]:
            async with self.db.sessions() as session, session.begin():
                first = await session.scalar(select(QueueTrack.id).where(QueueTrack.chat_id == chat_id).order_by(QueueTrack.position).limit(1))
                if first is not None:
                    await session.execute(delete(QueueTrack).where(QueueTrack.chat_id == chat_id, QueueTrack.id != first))

    async def control(self, chat_id, action, value=None):
        async with self.locks[chat_id]:
            assistant = self.active.get(chat_id)
            if not assistant:
                raise PlayerError('Nothing is playing.')
            if action == 'pause':
                await assistant.calls.pause(chat_id)
            elif action == 'resume':
                await assistant.calls.resume(chat_id)
            elif action == 'volume':
                if not isinstance(value, int) or not 1 <= value <= 200:
                    raise PlayerError('Volume must be between 1 and 200.')
                await assistant.calls.change_volume_call(chat_id, value)
                async with self.db.sessions() as session, session.begin():
                    (await session.get(Group, chat_id)).volume = value
            elif action == 'loop':
                async with self.db.sessions() as session, session.begin():
                    group = await session.get(Group, chat_id)
                    group.loop = not group.loop
                    return group.loop
            else:
                raise PlayerError('Unknown control.')

    async def favorite(self, chat_id, user_id):
        tracks = await self.queue(chat_id)
        if not tracks:
            raise PlayerError('Nothing is playing.')
        async with self.db.sessions() as session, session.begin():
            if not await session.get(Favorite, (user_id, tracks[0].source_id)):
                session.add(Favorite(user_id=user_id, source_id=tracks[0].source_id, title=tracks[0].title))

    async def ended(self, chat_id, assistant):
        # Ignore late events from a released assistant.
        if self.active.get(chat_id) is not assistant:
            return
        try:
            await self.advance(chat_id, repeat=True, expected_generation=self.generations[chat_id])
        except (PlayerError, SourceError) as exc:
            log.warning('Track advancement failed in %s: %s', chat_id, exc)

    async def disconnected(self, chat_id, assistant):
        async with self.locks[chat_id]:
            if self.active.get(chat_id) is not assistant:
                return
            self.active.pop(chat_id, None)
            self.generations[chat_id] += 1
            await self.pool.release(chat_id)
            try:
                await self._start(chat_id, exclude={assistant.name})
            except (PlayerError, SourceError) as exc:
                log.warning('Recovery failed in %s; queue retained: %s', chat_id, exc)

    async def restore(self):
        async with self.db.sessions() as session:
            ids = (await session.scalars(select(QueueTrack.chat_id).distinct())).all()
        for chat_id in ids:
            async with self.locks[chat_id]:
                try:
                    await self._start(chat_id)
                except (PlayerError, SourceError) as exc:
                    log.warning('Queue retained for group %s; restore failed: %s', chat_id, exc)

    async def shutdown(self):
        self.closed = True
        for chat_id in list(self.active):
            async with self.locks[chat_id]:
                await self._leave(chat_id)
