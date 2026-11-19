from hydrogram import enums
from akshita.bot import authorized
from akshita.config import Settings


class Bot:
    async def get_chat_member(self, chat, user):
        class Member:
            status = enums.ChatMemberStatus.MEMBER
        return Member()


async def test_authorization():
    assert await authorized(Bot(), -1, 1, 1)
    assert not await authorized(Bot(), -1, 2, 1)
    assert not await authorized(Bot(), -1, None, 1)


def test_secrets_hidden():
    settings = Settings(api_id=1, api_hash='hash-secret', bot_token='token-secret', owner_id=1, assistant_sessions='session-secret')
    assert 'session-secret' not in repr(settings)
    assert 'token-secret' not in repr(settings)


def test_logs_redact_secrets_and_stream_queries():
    import logging
    from akshita.logging_utils import SafeFormatter
    settings = Settings(api_id=1, api_hash='hash-secret', bot_token='token-secret', owner_id=1,
                        assistant_sessions='session-secret', database_url='postgresql+asyncpg://user:db-secret@host/db')
    formatter = SafeFormatter(settings)
    record = logging.LogRecord('test', logging.ERROR, '', 0, 'token-secret session-secret db-secret https://x.test/stream?signature=abc', (), None)
    result = formatter.format(record)
    for secret in ('token-secret', 'session-secret', 'db-secret', 'signature=abc'):
        assert secret not in result


def test_encrypted_sessions(tmp_path):
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    path = tmp_path / 'sessions.enc'
    path.write_bytes(Fernet(key).encrypt(b'one,two'))
    settings = Settings(api_id=1, api_hash='hash', bot_token='token', owner_id=1,
                        assistant_sessions='', assistant_sessions_file=str(path), assistant_key=key.decode())
    assert settings.sessions() == ['one', 'two']
    assert 'one,two' not in path.read_text()
