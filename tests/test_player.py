import asyncio
import pytest
from sqlalchemy import select
from akshita.assistants import Assistant, AssistantPool
from akshita.db import Favorite
from akshita.player import PlayerError, PlayerManager
from akshita.sources import SourceError, Track
from conftest import FakeCalls, FakeSource


def track(title, video=False):
    return Track('abcdefghijk', title, video=video)


async def test_multiple_groups_are_isolated(player):
    await asyncio.gather(player.enqueue(-1, track('one')), player.enqueue(-2, track('two', True)))
    assert player.active[-1] is not player.active[-2]
    await player.enqueue(-1, track('next'))
    await player.stop(-1)
    assert await player.queue(-1) == []
    assert (await player.queue(-2))[0].title == 'two'
    assert -2 in player.active
    assert -2 not in player.pool.assistants[1].calls.left


async def test_queue_advance_loop_clear_and_favorites(player, db):
    await player.enqueue(-1, track('first'))
    await player.enqueue(-1, track('second'))
    await player.favorite(-1, 123)
    await player.favorite(-1, 123)
    async with db.sessions() as session:
        assert len((await session.scalars(select(Favorite))).all()) == 1
    assert await player.control(-1, 'loop') is True
    await player.ended(-1, player.active[-1])
    assert (await player.queue(-1))[0].title == 'first'
    await player.advance(-1)
    assert (await player.queue(-1))[0].title == 'second'
    await player.clear(-1)
    assert len(await player.queue(-1)) == 1
    await player.advance(-1)
    assert -1 not in player.active


async def test_capacity_and_bounds(player):
    await asyncio.gather(*(player.enqueue(-1, track(str(i))) for i in range(3)))
    with pytest.raises(PlayerError, match='full'):
        await player.enqueue(-1, track('extra'))
    with pytest.raises(PlayerError, match='Volume'):
        await player.control(-1, 'volume', 201)


async def test_assistant_failover_on_start(db):
    bad, good = Assistant('bad', None, FakeCalls(True)), Assistant('good', None, FakeCalls())
    player = PlayerManager(db, FakeSource(), AssistantPool([bad, good]))
    await player.enqueue(-10, track('first'))
    assert player.active[-10] is good
    assert bad.chat_id is None
    await player.shutdown()
    assert good.chat_id is None
    assert len(await player.queue(-10)) == 1  # restart retains queue


async def test_failed_extraction_retains_queue(player):
    async def fail(_):
        raise SourceError('source unavailable')
    player.source.resolve = fail
    with pytest.raises(SourceError):
        await player.enqueue(-1, track('first'))
    assert len(await player.queue(-1)) == 1
    assert -1 not in player.active


async def test_restore_uses_fresh_extraction(db):
    source = FakeSource()
    assistant = Assistant('one', None, FakeCalls())
    old = PlayerManager(db, source, AssistantPool([assistant]))
    await old.enqueue(-1, track('persisted'))
    await old.shutdown()
    new = PlayerManager(db, source, AssistantPool([assistant]))
    await new.restore()
    assert -1 in new.active
    await new.shutdown()


async def test_disconnect_recovers_with_another_assistant(player):
    await player.enqueue(-1, track('first'))
    original = player.active[-1]
    await player.disconnected(-1, original)
    assert player.active[-1] is not original
    assert original.chat_id is None
    assert (await player.queue(-1))[0].title == 'first'


async def test_stale_generation_does_not_advance(player):
    await player.enqueue(-1, track('first'))
    await player.enqueue(-1, track('second'))
    old = player.generations[-1]
    await player.advance(-1)
    await player.advance(-1, repeat=True, expected_generation=old)
    assert (await player.queue(-1))[0].title == 'second'
