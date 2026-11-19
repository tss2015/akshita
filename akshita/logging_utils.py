"""Best-effort redaction for application and library log output."""
import logging
import re
from urllib.parse import unquote, urlsplit


class SafeFormatter(logging.Formatter):
    def __init__(self, settings):
        super().__init__('%(asctime)s %(levelname)s %(name)s %(message)s')
        db_password = urlsplit(settings.database_url).password
        self.secrets = [s for s in [settings.api_hash.get_secret_value(), settings.bot_token.get_secret_value(),
                                     settings.assistant_key.get_secret_value() if settings.assistant_key else '',
                                     *settings.sessions(), db_password or '', unquote(db_password) if db_password else ''] if s]

    def format(self, record):
        text = super().format(record)
        for secret in self.secrets:
            text = text.replace(secret, '[REDACTED]')
        # Expiring stream URLs can contain credentials in their query strings.
        return re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[REDACTED]', text)


def configure_logging(settings):
    handler = logging.StreamHandler()
    handler.setFormatter(SafeFormatter(settings))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
