FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* && useradd -m -u 10001 bot
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=bot:bot akshita ./akshita
COPY --chown=bot:bot migrations ./migrations
COPY --chown=bot:bot alembic.ini ./
COPY --chown=bot:bot scripts ./scripts
USER bot
CMD ["python", "-m", "akshita"]
