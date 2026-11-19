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

## Optional YouTube account access

By default yt-dlp works **without a YouTube account**. To optionally use an account, configure a private Netscape-format browser cookies file; this is a browser session, not a separate yt-dlp account or API key. This feature does not ask for your Google password or 2FA code and does not bypass DRM, subscriptions, region restrictions or other provider controls.

1. On a trusted computer, sign in to YouTube in a browser. Export its YouTube/Google cookies in **Netscape `cookies.txt` format** using a trusted local export method; see the [yt-dlp cookies FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp). An extension can access account sessions, so choose carefully. Export only the relevant cookies where possible. Do not paste cookies into Telegram, GitHub, logs or chat.
2. Transfer the file securely to the VPS **outside the repository**, for example `/etc/akshita/youtube-cookies.txt`. Restrict it to the bot service account, e.g. owner `akshita` and mode `600`, and make sure the service user can traverse the parent directories. The file grants account access: protect it like a password and keep it out of images, backups and version control unless they are appropriately secured.
3. Add `YTDLP_COOKIES_FILE=/etc/akshita/youtube-cookies.txt` to the service's protected environment file, then restart the bot. Leave it unset or empty to keep anonymous access. The bot validates the file at startup and reads it again for each extraction, so a safely replaced file is used on the next request. Changing the environment variable itself requires a restart. A missing or invalid configured file fails closed rather than falling back to anonymous mode.

The file is loaded into an in-memory cookie jar and is not rewritten by the bot. Only YouTube/Google-related cookie domains are used; unrelated entries are ignored. Credentials are not saved in the playback database or sent as unscoped FFmpeg headers. Expired or revoked cookies need a fresh export; a valid file format does not prove the account is signed in. Authentication is shared across all groups using this bot, so any permitted group admin may request videos accessible to that account. Use a dedicated account and limit group access. Providers can change behavior, challenge accounts, rate-limit or restrict playback even with cookies. This feature has **not been tested with a live YouTube account**.

For Docker Compose, set `YTDLP_COOKIES_FILE=/run/secrets/youtube-cookies.txt` in `.env` and add a read-only bind mount in a local Compose override:

```yaml
services:
  bot:
    volumes:
      - /etc/akshita/youtube-cookies.txt:/run/secrets/youtube-cookies.txt:ro
```

The host file must be readable by container UID 10001 and its parent directory must be traversable. Do not put the cookies inside the repository or image. To disable account access, unset the variable and restart; delete the exported file securely and revoke browser sessions if the file may have been exposed.

## Commands and permissions

`/start`, `/help` explain setup. In a group, administrators (or the configured owner) can use `/play <search or YouTube URL>`, `/vplay <search or URL>` (if enabled), `/pause`, `/resume`, `/skip`, `/stop` or `/end`, `/clear` (upcoming tracks only), `/volume 1–200`, `/loop`, and `/restart` (restarts the current queued track). `/queue` and `/nowplaying` show the queue to group members. Playback is admin-only to reduce abuse. Inline buttons independently recheck group admin permissions; favorites and queue viewing are available to members. A user's favorite is persisted but a browsing interface is not yet provided.

Owner-only `/stats`, `/system`, `/uptime`, `/activegroups`, `/activeplayers`, `/assistantstatus`, and `/performance` currently all show the same basic status summary. Counts report starts, including retries, not unique finished tracks. Status and database health do not prove the audio is playing. Increasing volume can cause clipping; use a conservative value, typically at or below 100.

## VPS using systemd

1. Provision an always-on Linux VPS; install Python 3.11, `python3.11-venv`, FFmpeg, Git, and optionally PostgreSQL. Use a dedicated unprivileged `akshita` account and a firewall. Do not rely on Actions runners for permanent streaming; the experimental rotation below is not a high-availability service.
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

### Experimental GitHub-hosted runner rotation

`.github/workflows/rotate-bot.yml` is an **opt-in experiment**, not a replacement for an always-on VPS. It requests a fresh runner every four hours (`17 */4 * * *`, UTC), plus manual runs. Each runner installs dependencies and can prepare while the previous slot is active. The rotation helper gives a slot 4 hours 10 minutes from the time the helper starts; the successor waits for a PostgreSQL advisory lock before migrating or starting the bot. The previous bot is asked to shut down, and its process group is cleaned up before the lock is released. Thus *runner preparation* can overlap, but **two bot processes are not intentionally run together**. The first slot can last up to 4h10; subsequent slots are normally about four hours if scheduling and setup times are consistent.

To configure it after merging this workflow into `main`:

1. Provision a **shared, persistent PostgreSQL database** reachable by the runners, with a database user allowed to apply migrations. SQLite is deliberately rejected: each hosted runner has an ephemeral filesystem, and SQLite cannot coordinate the handoff. Use a direct PostgreSQL connection or session-pooling endpoint; transaction pooling cannot safely hold a session-level advisory lock. Use TLS with certificate verification and network access appropriate for your provider; don't expose a database publicly without suitable access controls.
2. In GitHub repository **Settings → Secrets and variables → Actions**, create repository secrets `API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID`, `ASSISTANT_SESSIONS` and `DATABASE_URL`. The database URL must be in SQLAlchemy asyncpg form, such as `postgresql+asyncpg://USER:ENCODED_PASSWORD@HOST:5432/DB?ssl=verify-full`. Percent-encode special characters in credentials. Ensure the runner trusts the database certificate; your provider may require additional CA configuration. Never paste real secrets into the repository, PR, or chat.
3. Optionally add the `YOUTUBE_COOKIES` secret containing the Netscape-format cookie file described above. The workflow writes it to a temporary private runner file; do not use this optional secret unless you trust GitHub-hosted runners and repository administrators with that account. GitHub Actions has secret size limits; larger files need a separate secure secret store. Optionally set repository variable `VIDEO_ENABLED` to `true` after testing resources.
4. Create the **repository variable** `ACTIONS_BOT_ENABLED` with value `true` to opt in. Runs check this variable and the `main` branch; otherwise the job is skipped. The workflow is not invoked by pull requests. You may also start it from **Actions → Experimental bot rotation → Run workflow** on `main`. To stop future runs, set the variable to `false` or disable the workflow and cancel any active runs. A run already in progress does not automatically stop when the variable changes.
5. Use this workflow as the **only** launcher for this bot and these assistant accounts. A VPS service, manual bot process, or another deployment that does not acquire the same lock can run concurrently and conflict. All rotating runners must use the exact same PostgreSQL database. A GitHub manual run can wait for the current runner and take the next slot.

**Limitations:** GitHub schedules can be delayed, skipped or disabled; runner startup, dependency installation and migrations can exceed the overlap window. Jobs may be cancelled, hit execution or billing limits, or lose access to Telegram or the database. A failed bot does not automatically restart until another run is triggered. Playback is interrupted at handoff and restored queued tracks restart from the beginning. The advisory lock provides cooperative exclusion only while the database connection is healthy; a network partition or abrupt termination can release the database lock before the old process has fully stopped. Heartbeats reduce but cannot eliminate this split-brain window. The workflow does not provide fencing, seamless handoff or guaranteed continuous playback, and has not been tested with a live GitHub runner, PostgreSQL server or Telegram accounts. Monitor the Actions runs and use the VPS service for dependable operation.

## Backups and recovery

For PostgreSQL use `pg_dump` to a protected, encrypted backup location and regularly test `pg_restore` into a separate database before switching `DATABASE_URL`. For SQLite, use its online backup API or stop the service before copying the database; include WAL files if applicable. Back up ciphertext and its independently protected key separately. Before changing versions, snapshot the database and preserve the previous release. If migration fails, stop the service, restore a tested database backup and previous application version; do not assume a downgrade is lossless. `alembic current` and `alembic history` inspect migration state.

## Troubleshooting

- **No assistant available:** check startup logs for validation failures, capacity, session revocation, network, and that the assistant is a group member. Restart to retry validation. Never post session strings.
- **Playback cannot start:** check active group voice chat, permissions, FFmpeg/FFprobe, provider availability, and extraction restrictions. If optional cookies are configured, check their file format, permissions and expiry; never paste their contents into logs or support requests. The queue is retained; use `/restart` after resolving the issue or `/stop` to clear it.
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

Tests use simulated source/call clients, a simulated rotation lock, and temporary SQLite databases; they cover isolation, queue limits, event handling, startup/disconnect failover, persistence/restart, permissions, response validation, and anonymous and cookie-configured extraction wiring. They do **not** establish live API compatibility, video sync, FFmpeg crash behavior, transport quality, security under adversarial conditions, or realistic resource consumption. Run separate integration and endurance tests with test accounts, real voice chats and authorized provider access before deployment.
