# 🎧 AKSHITA MUSIC

**Your Music. Your Vibe. Your World.**  
**AKSHITA MUSIC — Made with ❤️ and Love from The Secret Squad**

An asynchronous Telegram group music bot foundation with persistent queues, YouTube discovery, multiple assistant accounts, and optional video through Hydrogram and PyTgCalls. The implementation targets minimal overhead and recovery, **not guaranteed zero latency, uninterrupted playback, or lossless Telegram transport**.

> **Project status: working foundation, not the complete production platform requested.** The core is implemented and tested with simulated assistants and media; it has **not** been tested against live Telegram voice chats, YouTube streaming, FFmpeg, a VPS, PostgreSQL, Docker, or provider APIs in this environment. Treat deployment as a pilot. See [Implemented and missing](#implemented-and-missing) before use.

## Implemented and missing

- Implemented: group-isolated, SQL-persisted bounded queues; YouTube search/single-video links and fresh stream extraction; audio and opt-in video media configuration; up to 10 exclusive assistant accounts; retry with another assistant when a start fails or Telegram reports an assistant kicked/removed; manual restart; pause/resume/skip/stop/clear/volume/loop; callback checks; favorites storage; history counts; owner status; encrypted session-file option; Alembic; deployment templates and mock-based tests.
- **Not implemented:** Spotify, Apple Music, SoundCloud, radio, Jamendo, Internet Archive, uploaded files or Subsonic adapters; playlist creation/sharing/import/export; viewing favorites/history; shuffle, skip-to, seek, replay, lyrics, song downloads; progress or now-playing cards with thumbnails; dynamic assistant administration or automatic revalidation; Redis coordination; stream prefetch/cache; automatic recovery from all network failures, expired URLs or FFmpeg crashes; comprehensive metrics and resource limits. Do not assume metadata APIs provide playable Spotify/Apple audio or bypass access controls.
- Recovery is limited: failed starts try another free assistant, kicked/removed assistants trigger a retry on another account, and queues are retained across shutdown/restart. It does not continuously monitor assistant/network health. A failed track is retained on start failure; use `/restart` or `/stop` after correcting the problem. End-of-stream events advance the queue, but the library does not attach a track ID; a sufficiently late event from a prior stream can still affect a replacement stream. FFmpeg errors may appear as an end event rather than a recoverable error.
- One process must own a deployment/database and assistant accounts. Locks and assignments are in memory, not distributed; do not scale multiple bot instances against the same accounts/database. Queue recovery restarts the current track from the beginning, not its previous position. Video audio/video synchronization and real resource use remain unverified. No load or endurance benchmarks have been run.
- The database currently contains groups, queue tracks, favorites and playback history, rather than the full requested schema. There are no durable per-user roles or assistant assignments; Telegram admins control playback. Encryption is available for session strings, but operator-managed encryption keys and Telegram/API secrets still need a separate protected secret store. The simple rate limiter is per-process, not a distributed abuse-control system.

## Requirements

- Python 3.11, FFmpeg and FFprobe on PATH, network access to Telegram and YouTube.
- Telegram API ID/hash from my.telegram.org; a bot token from BotFather; numeric owner user ID; **at least one authorized user assistant session**. The assistant and bot must already be members of each group, and a group voice chat should already be active. Set appropriate Telegram permissions.
- PostgreSQL is recommended for a VPS. SQLite is useful for development or a single small instance only. Do not use a network filesystem for SQLite.
- Use sources only where authorized and in accordance with their terms. YouTube extraction can break or be rate-limited; update and retest pinned packages as necessary. yt-dlp performs network extraction in bounded worker threads, not in the event loop. It does not download complete tracks in this workflow.

## Local setup

```sh
sudo apt-get update && sudo apt-get install -y python3.11-venv ffmpeg
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# Edit .env privately with actual credentials, owner ID and assistant sessions.
alembic upgrade head
python -m akshita
```

Obtain a Hydrogram-compatible user session using Hydrogram's documented authorization flow on a trusted machine. It grants access to the account: never send it to the bot, commit it, paste it into an issue, or include it in logs. The bot validates sessions by connecting at startup; at least one must connect. Assistant order is priority order; each assistant is reserved for at most one active group. Assistants that fail startup validation are omitted until restart. The bot does not automatically join assistants to groups.

For encrypted session storage, create a Fernet key on a trusted machine, store it in a separate secret manager, and set `ASSISTANT_KEY` only in the protected service environment. Run `python scripts/encrypt_sessions.py /secure/path/assistant-sessions.enc` with the key in that environment; enter comma-separated sessions at the hidden prompt. Set `ASSISTANT_SESSIONS_FILE` to the resulting file and leave `ASSISTANT_SESSIONS` empty. Restrict file/key access to the service user. Encryption does not protect against compromise of the running process or a host that can access both key and ciphertext. Rotate by generating a new key and encrypted file, securely switching both, then restarting. Credentials in plain `.env` are supported for development only; protect the file and host backups.

`DATABASE_URL` examples:

```text
sqlite+aiosqlite:///./akshita.db
postgresql+asyncpg://akshita:URL_ENCODED_PASSWORD@127.0.0.1:5432/akshita
```

Percent-encode special characters in the database password. The PostgreSQL database and user must exist before migration. Set `VIDEO_ENABLED=true` only after testing available CPU, bandwidth and group video-chat support. Audio is configured as 48 kHz stereo; video targets up to 720p/30 fps, with separate media inputs if the provider returns them. PyTgCalls/FFmpeg handle processing; Telegram may re-encode it.

## Commands and permissions

`/start`, `/help` explain setup. In a group, administrators (or the configured owner) can use `/play <search or YouTube URL>`, `/vplay <search or URL>` (if enabled), `/pause`, `/resume`, `/skip`, `/stop` or `/end`, `/clear` (upcoming tracks only), `/volume 1–200`, `/loop`, and `/restart` (restarts the current queued track). `/queue` and `/nowplaying` show the queue to group members. Playback is admin-only to reduce abuse. Inline buttons independently recheck group admin permissions; favorites and queue viewing are available to members. A user's favorite is persisted but a browsing interface is not yet provided.

Owner-only `/stats`, `/system`, `/uptime`, `/activegroups`, `/activeplayers`, `/assistantstatus`, and `/performance` currently all show the same basic status summary. Counts report starts, including retries, not unique finished tracks. Status and database health do not prove the audio is playing. Increasing volume can cause clipping; use a conservative value, typically at or below 100.

## VPS using systemd

1. Provision an always-on Linux VPS; install Python 3.11, `python3.11-venv`, FFmpeg, Git, and optionally PostgreSQL. Use a dedicated unprivileged `akshita` account and a firewall. Never run this bot on an Actions runner as a permanent service.
2. Place a dedicated main-branch deployment checkout at `/opt/akshita`, make the checkout and its `.venv` writable by `akshita`, and install `requirements.txt` as that user. Create `/var/lib/akshita` owned by `akshita`. Keep the secret environment file at `/etc/akshita/akshita.env`, owned by root with restricted read access for the service as appropriate. For SQLite use `sqlite+aiosqlite:////var/lib/akshita/akshita.db`; for production use PostgreSQL. Mount encrypted assistant files at a path readable by the service, and provide the key separately through your secret-management mechanism.
3. As an administrator, load the environment securely and run `/opt/akshita/.venv/bin/alembic upgrade head`. Install `deploy/akshita.service` at `/etc/systemd/system/akshita.service`. Adjust paths, permissions and hardening for your host. `systemctl daemon-reload && systemctl enable --now akshita`. View logs with `journalctl -u akshita -f` and set journal retention/rotation on the host.
4. Back up first, migrate before every upgrade, and validate with a real test group. Use `systemctl restart akshita` for configuration changes. The service stops calls gracefully on shutdown and leaves queues for the next start.

### Docker Compose

Set `.env`, including `DATABASE_URL` (for SQLite use `sqlite+aiosqlite:////data/akshita.db`), and create a data directory writable by container UID 10001: `mkdir -p data && sudo chown 10001:10001 data`. If using encrypted sessions, mount the ciphertext as a read-only secret and inject the key securely rather than baking either into the image. Run:

```sh
docker compose build
docker compose run --rm bot alembic upgrade head
docker compose up -d
```

Docker health checks only database connectivity and container liveness, not Telegram connectivity or actual media delivery. The Docker build and Compose configuration have not been exercised in this environment.

### GitHub Actions deployment

CI runs lint, unit tests, dependency checks, migrations, and Docker build. Deployment is **manual** through `workflow_dispatch` and uses a protected `production` environment. Provision `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, and verified `VPS_KNOWN_HOSTS` as GitHub environment secrets. Install `deploy/deploy-akshita` as root-owned `/usr/local/sbin/deploy-akshita`, review it carefully, and configure narrowly scoped sudo permission for this exact hook. The hook assumes a clean `/opt/akshita` checkout tracking `main`, reads the protected environment, installs dependencies, runs migrations and restarts systemd. It deploys the current VPS `origin/main`, **not** necessarily the workflow's selected commit. Restrict workflow/environment access and use an approval gate. A failed migration or health check fails deployment; it does not perform automated rollback. The hook sources the environment as shell code: only trusted operators may edit that file, and values must be shell-safe.

## Backups and recovery

For PostgreSQL use `pg_dump` to a protected, encrypted backup location and regularly test `pg_restore` into a separate database before switching `DATABASE_URL`. For SQLite, use its online backup API or stop the service before copying the database; include WAL files if applicable. Back up ciphertext and its independently protected key separately. Before changing versions, snapshot the database and preserve the previous release. If migration fails, stop the service, restore a tested database backup and previous application version; do not assume a downgrade is lossless. `alembic current` and `alembic history` inspect migration state.

## Troubleshooting

- **No assistant available:** check startup logs for validation failures, capacity, session revocation, network, and that the assistant is a group member. Restart to retry validation. Never post session strings.
- **Playback cannot start:** check active group voice chat, permissions, FFmpeg/FFprobe, provider availability, and extraction restrictions. The queue is retained; use `/restart` after resolving the issue or `/stop` to clear it.
- **Video fails or stutters:** disable video, test audio separately, and inspect VPS CPU/network and real group video support. There are no enforced video resource limits.
- **Database errors:** check URL, server reachability, permissions and `alembic current`. Healthcheck is `python scripts/healthcheck.py` with `DATABASE_URL` in the environment. The application does not independently retry every failed database transaction.
- **Leaked secret:** revoke the bot token or user sessions immediately, rotate credentials and encryption keys, and inspect access. Logging redacts configured credentials and URL query strings on a best-effort basis; never assume third-party output is perfectly sanitized.

## Development and verification

```sh
pip install -r requirements-dev.txt
ruff check .
pytest -q
alembic upgrade head && alembic check
pip check
```

Tests use simulated source/call clients and temporary SQLite databases; they cover isolation, queue limits, event handling, startup/disconnect failover, persistence/restart, permissions and response validation. They do **not** establish live API compatibility, video sync, FFmpeg crash behavior, transport quality, security under adversarial conditions, or realistic resource consumption. Run separate integration and endurance tests with test accounts, real voice chats and authorized provider access before deployment.
