from collections.abc import Iterator

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, **kwargs)
    return _engine


def set_engine(engine: Engine) -> None:
    """Dùng trong test để thay bằng SQLite."""
    global _engine
    _engine = engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def upsert(session: Session, model, rows: list[dict], keys: list[str], update: list[str] | None = None) -> int:
    """INSERT ... ON CONFLICT cho cả PostgreSQL (VPS) và SQLite (test).

    update=None  -> ON CONFLICT DO NOTHING (chống trùng khi Pi gửi lại outbox)
    update=[...] -> ON CONFLICT DO UPDATE các cột đó
    Trả về số dòng thực sự được thêm/cập nhật.
    """
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    stmt = insert(model.__table__).values(rows)
    if update:
        stmt = stmt.on_conflict_do_update(index_elements=keys, set_={c: stmt.excluded[c] for c in update})
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=keys)
    result = session.execute(stmt)
    return max(result.rowcount or 0, 0)


def create_all() -> None:
    from . import models  # noqa: F401  đăng ký bảng

    SQLModel.metadata.create_all(get_engine())
