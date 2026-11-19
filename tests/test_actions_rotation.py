import asyncio
import os
import sys
import time

import pytest

from scripts import actions_bot_rotation as rotation


class FakeDB:
    def __init__(self):
        self.busy = False
        self.owner = None

    def connection(self):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, db):
        self.db = db
        self.closed = False
        self.listener = None

    async def fetchval(self, query, *args, **kwargs):
        if 'pg_try_advisory_lock' in query:
            assert args == (rotation.LOCK_KEY,)
            if self.db.busy:
                return False
            self.db.busy = True
            self.db.owner = self
            return True
        return 1

    def add_termination_listener(self, listener):
        self.listener = listener

    def remove_termination_listener(self, listener):
        assert self.listener == listener
        self.listener = None

    def is_closed(self):
        return self.closed

    async def close(self, timeout):
        self.closed = True
        if self.db.owner is self:
            self.db.busy = False
            self.db.owner = None


def test_requires_postgres_and_all_secrets(monkeypatch):
    for name in ('API_ID', 'API_HASH', 'BOT_TOKEN', 'OWNER_ID', 'ASSISTANT_SESSIONS'):
        monkeypatch.setenv(name, 'example')
    monkeypatch.setenv('DATABASE_URL', 'sqlite+aiosqlite:///data.db')
    with pytest.raises(ValueError, match='PostgreSQL'):
        rotation.postgres_dsn()
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://user:password@host/db')
    assert rotation.postgres_dsn() == 'postgresql://user:password@host/db'
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://user:password@host/db?ssl=verify-full')
    assert rotation.postgres_dsn() == 'postgresql://user:password@host/db?sslmode=verify-full'
    monkeypatch.delenv('BOT_TOKEN')
    with pytest.raises(ValueError, match='BOT_TOKEN') as error:
        rotation.postgres_dsn()
    assert 'password' not in str(error.value)


async def test_prepared_runner_waits_until_previous_lock_is_released(monkeypatch):
    monkeypatch.setattr(rotation, 'MIN_ACTIVE_SECONDS', 0)
    db = FakeDB()
    first, second = db.connection(), db.connection()
    stop = asyncio.Event()
    deadline = time.monotonic() + 2
    assert await rotation.acquire_lock(first, stop, deadline, poll_seconds=0.01)
    waiting = asyncio.create_task(rotation.acquire_lock(second, stop, deadline, poll_seconds=0.01))
    await asyncio.sleep(0.04)
    assert not waiting.done()
    assert db.owner is first
    await first.close(timeout=1)
    assert await asyncio.wait_for(waiting, 1)
    assert db.owner is second
    await second.close(timeout=1)


async def test_waiting_runner_stops_without_starting(monkeypatch):
    monkeypatch.setattr(rotation, 'MIN_ACTIVE_SECONDS', 0)
    db = FakeDB()
    first, second = db.connection(), db.connection()
    stop = asyncio.Event()
    deadline = time.monotonic() + 2
    assert await rotation.acquire_lock(first, stop, deadline, poll_seconds=0.01)
    task = asyncio.create_task(rotation.acquire_lock(second, stop, deadline, poll_seconds=0.01))
    await asyncio.sleep(0.02)
    stop.set()
    assert not await asyncio.wait_for(task, 1)
    assert db.owner is first


async def test_no_stale_slot():
    conn = FakeDB().connection()
    assert not await rotation.acquire_lock(conn, asyncio.Event(), time.monotonic() + 1, poll_seconds=0.01)


async def test_lost_connection_stops_bot(monkeypatch):
    monkeypatch.setattr(rotation, 'HEARTBEAT_SECONDS', 0.01)
    class Broken:
        async def fetchval(self, *_args, **_kwargs):
            raise ConnectionError('password or secret')
    stop, lost = asyncio.Event(), asyncio.Event()
    await asyncio.wait_for(rotation.monitor_connection(Broken(), stop, lost), 1)
    assert stop.is_set() and lost.is_set()


async def test_child_stops_on_handoff(tmp_path):
    marker = tmp_path / 'running'
    command = [sys.executable, '-c', f'import pathlib,time; pathlib.Path({str(marker)!r}).touch(); time.sleep(30)']
    stop = asyncio.Event()
    task = asyncio.create_task(rotation.run_child(command, stop))
    for _ in range(100):
        if marker.exists():
            break
        await asyncio.sleep(0.01)
    assert marker.exists()
    stop.set()
    assert await asyncio.wait_for(task, 3) is None


async def test_early_child_exit_is_reported():
    result = await rotation.run_child([sys.executable, '-c', 'raise SystemExit(7)'], asyncio.Event())
    assert result == 7


async def test_full_handoff_holds_lock_through_child_shutdown(monkeypatch):
    monkeypatch.setattr(rotation, 'MIN_ACTIVE_SECONDS', 0)
    for name in ('API_ID', 'API_HASH', 'BOT_TOKEN', 'OWNER_ID', 'ASSISTANT_SESSIONS'):
        monkeypatch.setenv(name, 'example')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://user:pw@host/db')
    db, commands = FakeDB(), []
    conn = db.connection()

    async def connect(**kwargs):
        assert kwargs['dsn'] == 'postgresql://user:pw@host/db'
        return conn

    async def child(command, stop):
        assert db.owner is conn and not conn.closed
        commands.append(command)
        if command[-1] == 'akshita':
            stop.set()
            return None
        return 0

    monkeypatch.setattr(rotation.asyncpg, 'connect', connect)
    monkeypatch.setattr(rotation, 'run_child', child)
    assert await rotation.main() == 0
    assert commands == [[sys.executable, '-m', 'alembic', 'upgrade', 'head'], [sys.executable, '-m', 'akshita']]
    assert conn.closed and db.owner is None


def test_workflow_is_opt_in_and_uses_no_concurrency_cancellation():
    text = open(os.path.join('.github', 'workflows', 'rotate-bot.yml'), encoding='utf8').read()
    assert "vars.ACTIONS_BOT_ENABLED == 'true'" in text
    assert "cron: '17 */4 * * *'" in text
    assert 'cancel-in-progress' not in text


async def test_migration_failure_never_starts_bot(monkeypatch):
    monkeypatch.setattr(rotation, 'MIN_ACTIVE_SECONDS', 0)
    for name in ('API_ID', 'API_HASH', 'BOT_TOKEN', 'OWNER_ID', 'ASSISTANT_SESSIONS'):
        monkeypatch.setenv(name, 'example')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://user:pw@host/db')
    db, commands = FakeDB(), []
    conn = db.connection()

    async def connect(**kwargs):
        return conn

    async def child(command, stop):
        commands.append(command)
        assert db.owner is conn
        return 1

    monkeypatch.setattr(rotation.asyncpg, 'connect', connect)
    monkeypatch.setattr(rotation, 'run_child', child)
    assert await rotation.main() == 1
    assert commands == [[sys.executable, '-m', 'alembic', 'upgrade', 'head']]
    assert conn.closed and db.owner is None
