import pytest
from akshita.sources import SourceError, Track, YouTube, validate_query


def test_restrict_urls():
    assert validate_query('https://youtu.be/abcdefghijk?t=2') == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert validate_query('hello') == 'ytsearch1:hello'
    for value in ['http://localhost/admin', 'https://youtube.com.evil.test/watch?v=abcdefghijk', 'https://youtube.com/playlist?list=x', '', 'x' * 301]:
        with pytest.raises(SourceError):
            validate_query(value)


async def test_search_and_fresh_resolve(monkeypatch):
    source = YouTube()
    calls = []
    def extract(url, options):
        calls.append(url)
        return {'entries': [{'id': 'abcdefghijk', 'title': 'Song', 'duration': 12}]} if url.startswith('ytsearch') else {'url': 'https://media.example/temporary'}
    monkeypatch.setattr(source, '_extract', extract)
    track = await source.search('song')
    assert track == Track('abcdefghijk', 'Song', 12)
    assert (await source.resolve(track))[0] == 'https://media.example/temporary'
    await source.resolve(track)
    assert len(calls) == 3


async def test_provider_failure_and_invalid_response(monkeypatch):
    source = YouTube()
    def fail(*_):
        raise RuntimeError('secret in upstream error')
    monkeypatch.setattr(source, '_extract', fail)
    with pytest.raises(SourceError, match='Could not search') as error:
        await source.search('song')
    assert 'secret' not in str(error.value)
    monkeypatch.setattr(source, '_extract', lambda *_: {'id': 'bad'})
    with pytest.raises(SourceError):
        await source.search('song')


async def test_video_separate_inputs_and_invalid_url(monkeypatch):
    source = YouTube()
    track = Track('abcdefghijk', 'video', video=True)
    monkeypatch.setattr(source, '_extract', lambda *_: {'requested_formats': [{'url': 'https://media.example/video'}, {'url': 'https://media.example/audio'}], 'http_headers': {'User-Agent': 'test'}})
    video, audio, headers = await source.resolve(track)
    assert video.endswith('/video') and audio.endswith('/audio')
    assert headers['User-Agent'] == 'test'
    monkeypatch.setattr(source, '_extract', lambda *_: {'url': 'file:///etc/passwd'})
    with pytest.raises(SourceError):
        await source.resolve(track)
