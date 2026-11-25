from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from .settings import DATABASE_URL, REDIS_URL

sqlite = DATABASE_URL.startswith("sqlite")
options = {"pool_pre_ping": True}
if sqlite:
    options["connect_args"] = {"check_same_thread": False, "timeout": 30}
    if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"} or ":memory:" in DATABASE_URL:
        options["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **options)


if sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


from redis import Redis

cache = Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3)
