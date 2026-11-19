"""Check DB connectivity; Docker also checks whether the bot process is running."""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    engine = create_async_engine(os.environ.get('DATABASE_URL', 'sqlite+aiosqlite:///./akshita.db'), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text('SELECT 1'))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
