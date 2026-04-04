from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

import parameters

_engine = None
_session_factory: sessionmaker[Session] | None = None


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """SQLite does not create parent folders; missing dirs cause 'unable to open database file'."""
    if not database_url.startswith("sqlite"):
        return
    url = make_url(database_url)
    if url.drivername != "sqlite":
        return
    dbpath = url.database
    if not dbpath or dbpath == ":memory:":
        return
    parent = os.path.dirname(os.path.abspath(dbpath))
    if parent:
        os.makedirs(parent, exist_ok=True)


def get_engine():
    global _engine
    if _engine is None:
        connect_args: dict = {}
        if parameters.DATABASE_URL.startswith("sqlite"):
            _ensure_sqlite_parent_dir(parameters.DATABASE_URL)
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            parameters.DATABASE_URL,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
