import pytest
from akshita.assistants import Assistant, AssistantPool
from akshita.db import Base, Database
from akshita.player import PlayerManager
from akshita.sources import Track


class FakeCalls:
    def __init__(self, fail=False):
        self.fail = fail
        self.played = []
        self.left = []

    async def play(self, chat_id, stream):
        if self.fail:
            raise RuntimeError('connection failure')
        self.played.append(chat_id)

    async def leave_call(self, chat_id):
        self.left.append(chat_id)

    async def pause(self, chat_id):
        pass

    async def resume(self, chat_id):
        pass

    async def change_volume_call(self, chat_id, value):
        pass


class FakeSource:
    async def search(self, query, video=False):
        return Track('abcdefghijk', query, video=video)

    async def resolve(self, track):
        return 'https://example.com/audio', None, {}


@pytest.fixture
async def db(tmp_path):
    database = Database(f'sqlite+aiosqlite:///{tmp_path}/test.db')
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.close()


@pytest.fixture
async def player(db):
    pool = AssistantPool([Assistant('one', None, FakeCalls()), Assistant('two', None, FakeCalls())])
    manager = PlayerManager(db, FakeSource(), pool, 3)
    yield manager
    await manager.shutdown()
