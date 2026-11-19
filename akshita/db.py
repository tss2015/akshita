from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Group(Base):
    __tablename__ = 'groups'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    loop: Mapped[bool] = mapped_column(Boolean, default=False)
    volume: Mapped[int] = mapped_column(Integer, default=100)


class QueueTrack(Base):
    __tablename__ = 'queue_tracks'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('groups.id', ondelete='CASCADE'), index=True)
    position: Mapped[int] = mapped_column(Integer)
    source_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    video: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index('ix_queue_chat_position', 'chat_id', 'position', unique=True),)


class History(Base):
    __tablename__ = 'playback_history'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('groups.id', ondelete='CASCADE'), index=True)
    source_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))


class Favorite(Base):
    __tablename__ = 'favorites'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True)
        if url.startswith('sqlite'):
            @event.listens_for(self.engine.sync_engine, 'connect')
            def foreign_keys(connection, _record):
                cursor = connection.cursor()
                cursor.execute('PRAGMA foreign_keys=ON')
                cursor.close()
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self):
        await self.engine.dispose()

    async def ping(self):
        async with self.sessions() as session:
            await session.execute(select(1))


async def ensure_group(session: AsyncSession, chat_id: int) -> Group:
    group = await session.get(Group, chat_id)
    if group is None:
        group = Group(id=chat_id, loop=False, volume=100)
        session.add(group)
        await session.flush()
    return group
