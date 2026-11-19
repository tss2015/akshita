import asyncio
import logging
import shutil

from hydrogram import Client, idle
from pytgcalls import PyTgCalls, filters as call_filters
from pytgcalls.types import ChatUpdate, Device, StreamEnded

from .assistants import Assistant, AssistantPool
from .bot import install_handlers
from .config import Settings
from .db import Database
from .logging_utils import configure_logging
from .player import PlayerManager
from .sources import CookieFileError, YouTube

log = logging.getLogger(__name__)


async def main():
    settings = Settings()
    configure_logging(settings)
    # Third-party debug logs can contain sensitive request data.
    for name in ('hydrogram', 'pytgcalls', 'yt_dlp'):
        logging.getLogger(name).setLevel(logging.WARNING)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFmpeg and FFprobe are required on PATH')
    db = Database(settings.database_url)
    await db.ping()
    assistants = []
    bot = None
    player = None
    try:
        try:
            source = YouTube(settings.extraction_concurrency, settings.ytdlp_cookies_file)
        except CookieFileError:
            log.error('YouTube cookies file is unreadable or invalid; check the server configuration.')
            raise
        for number, session in enumerate(settings.sessions(), 1):
            client = Client(f'assistant-{number}', api_id=settings.api_id, api_hash=settings.api_hash.get_secret_value(), session_string=session, in_memory=True)
            try:
                await client.start()
                calls = PyTgCalls(client)
                await calls.start()
                assistants.append(Assistant(f'Assistant {number}', client, calls))
            except Exception as exc:
                log.error('Assistant %d failed validation (%s)', number, type(exc).__name__)
                if client.is_connected:
                    await client.stop()
        if not assistants:
            raise RuntimeError('No assistant could connect. Check sessions and network access.')
        pool = AssistantPool(assistants)
        player = PlayerManager(db, source, pool, settings.max_queue)
        for assistant in assistants:
            async def on_end(_client, update, assistant=assistant):
                await player.ended(update.chat_id, assistant)
            assistant.calls.on_update(call_filters.stream_end(StreamEnded.Type.AUDIO, Device.MICROPHONE))(on_end)
            async def on_disconnect(_client, update, assistant=assistant):
                await player.disconnected(update.chat_id, assistant)
            assistant.calls.on_update(call_filters.chat_update(
                ChatUpdate.Status.KICKED | ChatUpdate.Status.LEFT_GROUP
            ))(on_disconnect)
        bot = Client('akshita-bot', api_id=settings.api_id, api_hash=settings.api_hash.get_secret_value(), bot_token=settings.bot_token.get_secret_value(), in_memory=True)
        install_handlers(bot, player, settings, db, pool)
        await bot.start()
        log.info('AKSHITA MUSIC started with %d assistant(s)', len(assistants))
        await player.restore()
        await idle()
    finally:
        if player:
            await player.shutdown()
        if bot and bot.is_connected:
            await bot.stop()
        for assistant in assistants:
            if assistant.client.is_connected:
                await assistant.client.stop()
        await db.close()
        log.info('AKSHITA MUSIC stopped')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        # Do not print configuration values or upstream exceptions on startup.
        log.error('Startup failed (%s). Check configuration, database, and network.', type(exc).__name__)
        raise SystemExit(1) from None
