"""YouTube discovery and just-in-time extraction; only stable IDs are persisted."""
import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import yt_dlp

log = logging.getLogger(__name__)
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class Track:
    source_id: str
    title: str
    duration: int | None = None
    thumbnail: str | None = None
    video: bool = False

    @property
    def url(self):
        return f'https://www.youtube.com/watch?v={self.source_id}'


def validate_query(query: str) -> str:
    query = query.strip()
    if not query or len(query) > 300:
        raise SourceError('Provide a search term or YouTube video URL (up to 300 characters).')
    if '://' in query:
        parsed = urlparse(query)
        if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'music.youtube.com'):
            raise SourceError('Only YouTube video URLs are supported.')
        if parsed.hostname == 'youtu.be':
            ident = parsed.path.strip('/')
        elif parsed.path == '/watch':
            ident = parse_qs(parsed.query).get('v', [''])[0]
        elif parsed.path.startswith(('/shorts/', '/live/')):
            ident = parsed.path.split('/')[2]
        else:
            ident = ''
        if not VIDEO_ID.fullmatch(ident):
            raise SourceError('Provide a single valid YouTube video URL.')
        return f'https://www.youtube.com/watch?v={ident}'
    return 'ytsearch1:' + query


class YouTube:
    def __init__(self, concurrency: int = 3):
        self.limit = asyncio.Semaphore(concurrency)

    async def search(self, query: str, video: bool = False) -> Track:
        target = validate_query(query)
        async with self.limit:
            try:
                data = await asyncio.to_thread(self._extract, target, {'extract_flat': True})
            except Exception as exc:
                log.warning('YouTube discovery failed (%s)', type(exc).__name__)
                raise SourceError('Could not search YouTube. Please try again later.') from exc
        if not isinstance(data, dict):
            raise SourceError('No track found.')
        if 'entries' in data:
            data = next((x for x in data['entries'] or [] if x), None)
        if not isinstance(data, dict) or not VIDEO_ID.fullmatch(str(data.get('id', ''))):
            raise SourceError('No playable YouTube video found.')
        duration = data.get('duration')
        thumbnail = data.get('thumbnail')
        return Track(data['id'], str(data.get('title') or 'Untitled')[:500],
                     int(duration) if isinstance(duration, (int, float)) and duration >= 0 else None,
                     thumbnail[:2048] if isinstance(thumbnail, str) and thumbnail.startswith('https://') else None, video)

    async def resolve(self, track: Track) -> tuple[str, str | None, dict]:
        # Separate streams are passed to MediaStream for video. Never persist these URLs.
        opts = {'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]' if track.video else 'bestaudio/best', 'noplaylist': True}
        async with self.limit:
            try:
                data = await asyncio.to_thread(self._extract, track.url, opts)
            except Exception as exc:
                log.warning('YouTube extraction failed (%s)', type(exc).__name__)
                raise SourceError('The track is unavailable or cannot be extracted.') from exc
        if not isinstance(data, dict):
            raise SourceError('Invalid response from media provider.')
        formats = data.get('requested_formats') or [data]
        if not isinstance(formats, list) or not formats:
            raise SourceError('No playable stream found.')
        urls = [f.get('url') for f in formats if isinstance(f, dict)]
        if not urls or any(not isinstance(u, str) or not u.startswith('https://') for u in urls):
            raise SourceError('Provider returned an invalid stream URL.')
        headers = data.get('http_headers') or {}
        return urls[0], urls[1] if len(urls) > 1 else None, headers

    @staticmethod
    def _extract(target, options):
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'socket_timeout': 15, 'noplaylist': True, **options}) as ydl:
            return ydl.extract_info(target, download=False)
