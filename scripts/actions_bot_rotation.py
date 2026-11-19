"""Experimental Actions handoff: one PostgreSQL advisory-lock owner per database.

The job is scheduled every four hours, while each prepared runner's slot expires
4h10m after this process starts. A successor may prepare early, but must wait for
the previous process and its child group to stop before acquiring the lock.
"""
import asyncio
import logging
import os
import signal
import sys
import time

import asyncpg
from sqlalchemy.engine import make_url

LOG = logging.getLogger('rotation')
LOCK_KEY = 4704921813992721457  # Stable signed bigint; shared by every runner of this bot.
SLOT_SECONDS = 250 * 60
MIN_ACTIVE_SECONDS = 180
POLL_SECONDS = 5
HEARTBEAT_SECONDS = 10
SHUTDOWN_SECONDS = 20


def postgres_dsn():
    url = os.environ.get('DATABASE_URL', '')
    if not url.startswith('postgresql+asyncpg://'):
        raise ValueError('This workflow requires a shared PostgreSQL DATABASE_URL.')
    for name in ('API_ID', 'API_HASH', 'BOT_TOKEN', 'OWNER_ID', 'ASSISTANT_SESSIONS'):
        if not os.environ.get(name):
            raise ValueError(f'Missing required secret: {name}.')
    # SQLAlchemy passes ?ssl=... as a keyword, whereas asyncpg's DSN
    # accepts the same setting as ?sslmode=.... Keep both connections aligned.
    parsed = make_url(url)
    query = dict(parsed.query)
    if 'sslmode' in query:
        raise ValueError('Use the SQLAlchemy-compatible ssl parameter, not sslmode.')
    if 'ssl' in query:
        query['sslmode'] = query.pop('ssl')
    query.pop('prepared_statement_cache_size', None)  # SQLAlchemy-only setting
    return parsed.set(drivername='postgresql', query=query).render_as_string(hide_password=False)


async def wait_for_stop(stop, seconds):
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(0, seconds))
        return True
    except TimeoutError:
        return False


async def acquire_lock(conn, stop, deadline, poll_seconds=POLL_SECONDS):
    """Never start a stale runner that has too little time left in its slot."""
    while not stop.is_set() and time.monotonic() + MIN_ACTIVE_SECONDS < deadline:
        if await conn.fetchval('SELECT pg_try_advisory_lock($1::bigint)', LOCK_KEY, timeout=5):
            return True
        await wait_for_stop(stop, min(poll_seconds, max(0, deadline - time.monotonic())))
    return False


async def monitor_connection(conn, stop, lost):
    while not await wait_for_stop(stop, HEARTBEAT_SECONDS):
        try:
            await conn.fetchval('SELECT 1', timeout=5)
        except Exception as exc:
            LOG.error('Lock connection health check failed (%s). Stopping the bot.', type(exc).__name__)
            lost.set()
            stop.set()
            return


async def stop_group(proc):
    # A dedicated process group includes the bot and normally its media subprocesses.
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=SHUTDOWN_SECONDS)
        except TimeoutError:
            LOG.warning('Graceful shutdown timed out; killing the process group.')
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await proc.wait()


async def run_child(command, stop):
    """Wait for completion or stop; always clean up before releasing the lock."""
    if stop.is_set():
        return None
    proc = await asyncio.create_subprocess_exec(*command, start_new_session=True)
    waiter = asyncio.create_task(proc.wait())
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait((waiter, stopping), return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            return None
        return waiter.result()
    finally:
        stopping.cancel()
        try:
            await stop_group(proc)
        finally:
            await asyncio.gather(waiter, stopping, return_exceptions=True)


async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    dsn = postgres_dsn()
    deadline = time.monotonic() + SLOT_SECONDS
    stop, lost = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    timer = loop.call_later(SLOT_SECONDS, stop.set)
    conn = None
    monitor = None
    terminated = None
    try:
        conn = await asyncpg.connect(dsn=dsn, timeout=15, command_timeout=10)
        def terminated(_connection):
            LOG.error('Lock connection terminated. Stopping the bot.')
            lost.set()
            stop.set()
        conn.add_termination_listener(terminated)
        LOG.info('Waiting for the previous slot to release its PostgreSQL lock.')
        if not await acquire_lock(conn, stop, deadline):
            LOG.warning('No streaming slot acquired before the deadline or shutdown.')
            return 1
        LOG.info('Lock acquired. Applying database migrations.')
        monitor = asyncio.create_task(monitor_connection(conn, stop, lost))
        result = await run_child([sys.executable, '-m', 'alembic', 'upgrade', 'head'], stop)
        if result != 0:
            LOG.error('Migration did not complete successfully; refusing to start the bot.')
            return 1
        if stop.is_set() or time.monotonic() + MIN_ACTIVE_SECONDS >= deadline:
            LOG.warning('Insufficient time remains in this slot; not starting the bot.')
            return 1
        LOG.info('Starting bot; it will stop before the next handoff.')
        result = await run_child([sys.executable, '-m', 'akshita'], stop)
        if lost.is_set():
            return 1
        if result is not None:
            LOG.error('Bot exited unexpectedly (status %s).', result)
            return 1
        LOG.info('Bot stopped for handoff or job shutdown.')
        return 0
    finally:
        timer.cancel()
        stop.set()
        if monitor:
            await monitor
        if conn and not conn.is_closed():
            # Closing the connection releases the session lock only after child cleanup.
            if terminated:
                conn.remove_termination_listener(terminated)
            await conn.close(timeout=5)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        # Driver exceptions may include connection details; never print them verbatim.
        LOG.error('Rotation failed (%s); check configuration and database connectivity.', type(exc).__name__)
        raise SystemExit(1) from None
