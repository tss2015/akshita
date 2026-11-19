import asyncio
import logging

import pytest
import yt_dlp

from akshita.config import Settings
from akshita.sources import CookieFileError, SourceError, YouTube, load_youtube_cookies


COOKIE = 'sensitive-fake-cookie-value'


def cookie_file(value=COOKIE):
    return ('# Netscape HTTP Cookie File\n'
            f'#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{value}\n'
            '.example.com\tTRUE\t/\tTRUE\t0\tOTHER\tprivate-other-site\n')


def test_read_cookie_file_filters_domains_and_never_writes(tmp_path):
    path = tmp_path / 'cookies.txt'
    original = cookie_file()
    path.write_text(original)
    cookies = load_youtube_cookies(str(path))
    assert len(cookies) == 1
    assert cookies[0].domain == '.youtube.com'
    assert cookies[0].value == COOKIE
    assert cookies[0].discard is True
    assert cookies[0].has_nonstandard_attr('HttpOnly')
    assert path.read_text() == original


async def test_authentication_search_and_playback_and_rotation(monkeypatch, tmp_path):
    path = tmp_path / 'cookies.txt'
    path.write_text(cookie_file())
    provider = YouTube(cookies_file=str(path))
    seen = []

    def extract(self, target, download):
        assert download is False
        assert self.params.get('cookiefile') is None
        seen.append([c.value for c in self.cookiejar])
        if target.startswith('ytsearch'):
            return {'entries': [{'id': 'abcdefghijk', 'title': 'Song'}]}
        return {'url': 'https://media.example/temporary',
                'http_headers': {'User-Agent': 'test', 'Cookie': 'sid=secret', 'Authorization': 'secret'}}

    monkeypatch.setattr(yt_dlp.YoutubeDL, 'extract_info', extract)
    track = await provider.search('song')
    path.write_text(cookie_file('rotated-cookie'))
    _, _, headers = await provider.resolve(track)
    assert seen == [[COOKIE], ['rotated-cookie']]
    assert headers == {'User-Agent': 'test'}
    assert path.read_text() == cookie_file('rotated-cookie')


async def test_anonymous_default_and_parallel_cookie_jars(monkeypatch, tmp_path):
    path = tmp_path / 'cookies.txt'
    path.write_text(cookie_file())
    seen = []

    def extract(self, target, download):
        seen.append((self.params.get('cookiefile'), [c.value for c in self.cookiejar]))
        return {'entries': [{'id': 'abcdefghijk', 'title': 'Song'}]}

    monkeypatch.setattr(yt_dlp.YoutubeDL, 'extract_info', extract)
    anonymous = YouTube()
    authenticated = YouTube(cookies_file=str(path))
    await asyncio.gather(anonymous.search('song'), authenticated.search('song'), authenticated.search('song'))
    assert (None, []) in seen
    assert seen.count((None, [COOKIE])) == 2
    assert path.read_text() == cookie_file()


def test_configuration_reads_env(monkeypatch):
    monkeypatch.setenv('YTDLP_COOKIES_FILE', '/private/cookies.txt')
    settings = Settings(api_id=1, api_hash='hash', bot_token='token', owner_id=1, assistant_sessions='session')
    assert settings.ytdlp_cookies_file == '/private/cookies.txt'


@pytest.mark.parametrize('content', [
    'not a netscape file',
    '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\tinvalid\tSID\tsecret',
    '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\textra',
    '# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tSID\tsecret',
])
def test_invalid_cookie_file_fails_closed_without_disclosing_contents(tmp_path, content, caplog, capsys):
    path = tmp_path / 'private.txt'
    path.write_text(content)
    with caplog.at_level(logging.DEBUG), pytest.raises(CookieFileError) as error:
        YouTube(cookies_file=str(path))
    assert 'secret' not in str(error.value)
    assert 'secret' not in caplog.text
    assert 'secret' not in capsys.readouterr().err


async def test_removed_cookie_file_does_not_fall_back_to_anonymous(tmp_path):
    path = tmp_path / 'cookies.txt'
    path.write_text(cookie_file())
    provider = YouTube(cookies_file=str(path))
    path.unlink()
    with pytest.raises(SourceError, match='cookies are unavailable or invalid'):
        await provider.search('song')


def test_missing_cookie_file_fails_startup(tmp_path):
    with pytest.raises(CookieFileError):
        YouTube(cookies_file=str(tmp_path / 'missing.txt'))


def test_youtube_cookie_domain_scoping(tmp_path):
    from http.cookiejar import CookieJar
    from urllib.request import Request

    path = tmp_path / 'cookies.txt'
    path.write_text(cookie_file())
    jar = CookieJar()
    for cookie in load_youtube_cookies(str(path)):
        jar.set_cookie(cookie)
    youtube = Request('https://www.youtube.com/watch?v=abcdefghijk')
    unrelated = Request('https://example.com/')
    jar.add_cookie_header(youtube)
    jar.add_cookie_header(unrelated)
    assert COOKIE in youtube.get_header('Cookie')
    assert unrelated.get_header('Cookie') is None
