from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(settings.database_url)

if engine.url.get_backend_name() == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        # Referential integrity is off by default in SQLite.
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets the API read while the worker writes, and it survives
        # crashes better than the default rollback journal.  In-memory
        # databases report "memory" and are left untouched.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Durability/throughput trade-off recommended by SQLite for WAL.
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Wait instead of failing immediately when another writer holds the lock.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def optimize_database() -> None:
    """Refresh query-planner statistics (SQLite's recommended maintenance).

    SQLite only switches to the covering index introduced by migration 0007
    once it has statistics for the table, and by default it never updates them.
    ``PRAGMA optimize`` is cheap, safe to run repeatedly and a no-op on other
    backends.
    """

    if engine.url.get_backend_name() != "sqlite":
        return
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA optimize"))
