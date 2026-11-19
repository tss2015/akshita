import html
import logging
import time

import psutil
from hydrogram import Client, enums, filters
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from .db import History
from .player import PlayerError
from .sources import SourceError

log = logging.getLogger(__name__)
BRAND = '🎧 <b>AKSHITA MUSIC</b>\nYour Music. Your Vibe. Your World.\n\nMade with ❤️ and Love from The Secret Squad'
KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton('⏸ Pause', callback_data='music:pause'), InlineKeyboardButton('▶️ Resume', callback_data='music:resume'), InlineKeyboardButton('⏭ Skip', callback_data='music:skip')],
    [InlineKeyboardButton('⏹ Stop', callback_data='music:stop'), InlineKeyboardButton('🔁 Loop', callback_data='music:loop'), InlineKeyboardButton('📃 Queue', callback_data='music:queue')],
    [InlineKeyboardButton('❤️ Favourite', callback_data='music:favorite')],
])


async def authorized(bot, chat_id, user_id, owner_id):
    if not user_id:
        return False
    if user_id == owner_id:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER)
    except Exception as exc:
        log.warning('Permission check failed (%s)', type(exc).__name__)
        return False


def install_handlers(bot: Client, player, settings, db, pool):
    started = time.monotonic()
    rates = {}

    def rate_limited(user_id):
        now = time.monotonic()
        # Periodic pruning keeps this bounded to recently active users.
        if len(rates) > 5000:
            rates.clear()
        if now - rates.get(user_id, 0) < 2:
            return True
        rates[user_id] = now
        return False

    async def render_queue(chat_id):
        tracks = await player.queue(chat_id)
        if not tracks:
            return '🎧 Queue is empty.'
        lines = [f'{i}. {html.escape(t.title)}' + (' 🎬' if t.video else '') for i, t in enumerate(tracks[:20], 1)]
        if len(tracks) > 20:
            lines.append(f'… and {len(tracks) - 20} more')
        return '🎧 <b>AKSHITA MUSIC · Queue</b>\n\n' + '\n'.join(lines)

    @bot.on_message(filters.command(['start', 'help']))
    async def help_command(_, message):
        await message.reply_text(BRAND + '\n\nGroup commands: /play, /vplay, /queue, /nowplaying, /pause, /resume, /skip, /stop, /clear, /volume, /loop, /restart. Playback controls require a group administrator. The assistant must already belong to the group and a voice chat must be active.', parse_mode=enums.ParseMode.HTML)

    @bot.on_message(filters.group & filters.command(['play', 'vplay', 'queue', 'nowplaying', 'pause', 'resume', 'skip', 'stop', 'end', 'clear', 'volume', 'loop', 'restart']))
    async def commands(_, message):
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else None
        cmd = message.command[0].lower()
        if not user_id:
            await message.reply_text('Please use a personal account for playback commands.')
            return
        if rate_limited(user_id):
            await message.reply_text('Please wait a moment before your next request.')
            return
        if cmd not in ('queue', 'nowplaying') and not await authorized(bot, chat_id, user_id, settings.owner_id):
            await message.reply_text('Only group administrators can control playback.')
            return
        try:
            if cmd in ('play', 'vplay'):
                if cmd == 'vplay' and not settings.video_enabled:
                    raise PlayerError('Video is disabled by the operator.')
                query = message.text.split(maxsplit=1)
                if len(query) < 2:
                    raise PlayerError('Provide a YouTube search or video URL.')
                track = await player.source.search(query[1], video=cmd == 'vplay')
                position = await player.enqueue(chat_id, track)
                await message.reply_text(f'🎧 <b>AKSHITA MUSIC</b>\n{html.escape(track.title)}\n' + ('Now playing' if position == 1 else f'Queued at #{position}'), parse_mode=enums.ParseMode.HTML, reply_markup=KEYBOARD)
            elif cmd in ('queue', 'nowplaying'):
                await message.reply_text(await render_queue(chat_id), parse_mode=enums.ParseMode.HTML, reply_markup=KEYBOARD)
            elif cmd == 'skip':
                await player.advance(chat_id)
                await message.reply_text('⏭ Skipped.\n' + await render_queue(chat_id), parse_mode=enums.ParseMode.HTML, reply_markup=KEYBOARD)
            elif cmd in ('stop', 'end'):
                await player.stop(chat_id)
                await message.reply_text('⏹ Playback stopped and queue cleared.')
            elif cmd == 'restart':
                await player.retry(chat_id)
                await message.reply_text('🎧 Playback restarted from the current track.')
            elif cmd == 'clear':
                await player.clear(chat_id)
                await message.reply_text('📃 Upcoming tracks cleared.')
            else:
                value = None
                if cmd == 'volume':
                    try:
                        value = int(message.command[1])
                    except (ValueError, IndexError):
                        raise PlayerError('Usage: /volume 1–200') from None
                result = await player.control(chat_id, cmd, value)
                await message.reply_text(f'🎧 {cmd.title()}' + (f': {"on" if result else "off"}' if cmd == 'loop' else ' ✓'))
        except (PlayerError, SourceError) as exc:
            await message.reply_text(f'⚠️ {exc}')
        except Exception as exc:
            log.error('Command failed (%s)', type(exc).__name__)
            await message.reply_text('⚠️ Playback failed. Check the voice chat and try again.')

    @bot.on_callback_query(filters.regex(r'^music:(pause|resume|skip|stop|loop|queue|favorite)$'))
    async def callback(_, query):
        if not query.message or query.message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP) or not query.from_user:
            await query.answer('This control is only available in groups.', show_alert=True)
            return
        chat_id, user_id = query.message.chat.id, query.from_user.id
        action = query.data.split(':', 1)[1]
        if rate_limited(user_id):
            await query.answer('Please wait a moment.', show_alert=True)
            return
        if action not in ('queue', 'favorite') and not await authorized(bot, chat_id, user_id, settings.owner_id):
            await query.answer('Group administrator access required.', show_alert=True)
            return
        try:
            if action == 'queue':
                await query.message.reply_text(await render_queue(chat_id), parse_mode=enums.ParseMode.HTML)
            elif action == 'favorite':
                await player.favorite(chat_id, user_id)
            elif action == 'skip':
                await player.advance(chat_id)
            elif action == 'stop':
                await player.stop(chat_id)
            else:
                await player.control(chat_id, action)
            await query.answer('Done')
        except (PlayerError, SourceError) as exc:
            await query.answer(str(exc), show_alert=True)
        except Exception as exc:
            log.error('Callback failed (%s)', type(exc).__name__)
            await query.answer('Could not complete that action.', show_alert=True)

    @bot.on_message(filters.command(['stats', 'system', 'uptime', 'assistantstatus', 'activegroups', 'activeplayers', 'performance']))
    async def status(_, message):
        if not message.from_user or message.from_user.id != settings.owner_id:
            await message.reply_text('Owner access required.')
            return
        try:
            await db.ping()
            async with db.sessions() as session:
                count = await session.scalar(select(func.count()).select_from(History))
            assistants = '\n'.join(f'{a.name}: {"available" if a.healthy else "unavailable"}' + (' (assigned)' if a.chat_id is not None else '') for a in pool.assistants)
            await message.reply_text(f'🎧 AKSHITA MUSIC\nActive players: {len(player.active)}\nTracks started: {count}\nCPU: {psutil.cpu_percent()}% · RAM: {psutil.virtual_memory().percent}%\nUptime: {int(time.monotonic() - started)}s\nDatabase: connected\n\n{assistants}')
        except Exception as exc:
            log.error('Status failed (%s)', type(exc).__name__)
            await message.reply_text('⚠️ Status unavailable; check service logs.')
