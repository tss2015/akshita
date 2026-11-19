"""YouTube discovery and just-in-time extraction; only stable IDs are persisted."""
import asyncio
import logging
import re
from dataclasses import dataclass
from http.cookiejar import Cookie
from pathlib import Path
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


class CookieFileError(Exception):
    """Cookie file unavailable or malformed; details must not include credentials."""


COOKIE_DOMAINS = ('youtube.com', 'google.com', 'googlevideo.com', 'ytimg.com')


def load_youtube_cookies(path: str) -> list[Cookie]:
    """Read a Netscape cookie file without logging its contents or writing to it."""
    try:
        with Path(path).open('rb') as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('file too large')
        lines = raw.decode('utf-8-sig').splitlines()
        if not lines or not lines[0].startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
            raise ValueError('invalid header')
        cookies = []
        for line in lines[1:]:
            http_only = line.startswith('#HttpOnly_')
            if http_only:
                line = line[len('#HttpOnly_'):]
            elif not line.strip() or line.startswith('#'):
                continue
            fields = line.split('\t')
            if len(fields) != 7:
                raise ValueError('invalid cookie record')
            domain, subdomains, cookie_path, secure, expiry, name, value = fields
            host = domain.lstrip('.').lower()
            if not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)+', host):
                raise ValueError('invalid domain')
            if subdomains not in ('TRUE', 'FALSE') or secure not in ('TRUE', 'FALSE'):
                raise ValueError('invalid flags')
            if (subdomains == 'TRUE') != domain.startswith('.') or not cookie_path.startswith('/') or not name:
                raise ValueError('invalid cookie record')
            if expiry and not expiry.isdigit():
                raise ValueError('invalid expiry')
            if not any(host == allowed or host.endswith('.' + allowed) for allowed in COOKIE_DOMAINS):
                continue
            expires = int(expiry) if expiry and int(expiry) else None
            cookies.append(Cookie(version=0, name=name, value=value, port=None, port_specified=False,
                                  domain=domain, domain_specified=subdomains == 'TRUE',
                                  domain_initial_dot=domain.startswith('.'), path=cookie_path,
                                  path_specified=True, secure=secure == 'TRUE', expires=expires,
                                  discard=expires is None, comment=None, comment_url=None,
                                  rest={'HttpOnly': None} if http_only else {}, rfc2109=False))
        if not cookies:
            raise ValueError('no YouTube or Google cookies')
        return cookies
    except (OSError, UnicodeError, ValueError, OverflowError) as exc:
        raise CookieFileError('YouTube cookies file is unreadable or invalid. Check the server configuration.') from exc


class SafeYtdlpLogger:
    """yt-dlp diagnostics can contain cookie values or media URLs; don't log them verbatim."""
    def debug(self, _message):
        pass

    def warning(self, _message):
        log.warning('yt-dlp reported a warning during extraction')

    def error(self, _message):
        log.warning('yt-dlp reported an extraction error')


class YouTube:
    def __init__(self, concurrency: int = 3, cookies_file: str | None = None):
        self.limit = asyncio.Semaphore(concurrency)
        self.cookies_file = cookies_file or None
        if self.cookies_file:
            load_youtube_cookies(self.cookies_file)

    async def search(self, query: str, video: bool = False) -> Track:
        target = validate_query(query)
        async with self.limit:
            try:
                data = await asyncio.to_thread(self._extract, target, {'extract_flat': True})
            except CookieFileError as exc:
                log.warning('YouTube cookies file became unavailable or invalid')
                raise SourceError('YouTube account cookies are unavailable or invalid; contact the bot owner.') from exc
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
            except CookieFileError as exc:
                log.warning('YouTube cookies file became unavailable or invalid')
                raise SourceError('YouTube account cookies are unavailable or invalid; contact the bot owner.') from exc
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
        # Never pass account credentials as unscoped FFmpeg headers.
        raw_headers = data.get('http_headers') or {}
        if not isinstance(raw_headers, dict):
            raise SourceError('Provider returned invalid media headers.')
        allowed = {'user-agent', 'accept', 'accept-language', 'referer', 'origin'}
        headers = {key: value for key, value in raw_headers.items()
                   if isinstance(key, str) and key.lower() in allowed and isinstance(value, str)
                   and '\r' not in value and '\n' not in value}
        return urls[0], urls[1] if len(urls) > 1 else None, headers

    def _extract(self, target, options):
        # Populate an in-memory jar instead of yt-dlp's cookiefile option: the latter
        # saves cookies on close, which would mutate the secret and race across threads.
        cookies = load_youtube_cookies(self.cookies_file) if self.cookies_file else []
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'socket_timeout': 15,
                               'noplaylist': True, 'logger': SafeYtdlpLogger(), **options}) as ydl:
            for cookie in cookies:
                ydl.cookiejar.set_cookie(cookie)
            return ydl.extract_info(target, download=False)
