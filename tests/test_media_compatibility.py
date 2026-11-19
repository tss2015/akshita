import asyncio
from hydrogram import Client
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream, VideoQuality


async def test_installed_library_media_api():
    stream = MediaStream('https://example.com/video', audio_path='https://example.com/audio',
                         audio_parameters=AudioQuality.HIGH, video_parameters=VideoQuality.HD_720p,
                         audio_flags=MediaStream.Flags.REQUIRED, video_flags=MediaStream.Flags.REQUIRED)
    assert stream.microphone.parameters.bitrate == 48000
    assert stream.microphone.parameters.channels == 2
    assert stream.camera.parameters.height == 720
    client = Client('test', api_id=1, api_hash='example', in_memory=True)
    PyTgCalls(client)._env_checker.check_environment()
    await asyncio.sleep(0)
