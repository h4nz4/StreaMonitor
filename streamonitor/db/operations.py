from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import parameters
from sqlalchemy import select

from streamonitor.db.models import Base, RecordingRow, StatusEventRow, StreamerRow
from streamonitor.db.session import get_engine, session_scope
import streamonitor.log as log

if TYPE_CHECKING:
    from streamonitor.bot import Bot

logger = log.Logger("[DB]").get_logger()


def init_database() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def _downloads_root() -> str:
    return os.path.abspath(parameters.DOWNLOADS_DIR)


def _relative_download_path(abs_path: str) -> str:
    root = _downloads_root()
    try:
        return os.path.relpath(abs_path, root)
    except ValueError:
        return abs_path


def upsert_streamer_row(session, bot: Bot) -> StreamerRow:
    data = bot.export()
    username = data["username"]
    site = data["site"]
    row = session.scalars(
        select(StreamerRow).where(StreamerRow.username == username, StreamerRow.site == site)
    ).first()
    now = datetime.now(timezone.utc)
    gender = data.get("gender")
    if gender is not None:
        gender = str(gender)
    fields = {
        "running": bool(data.get("running", False)),
        "country": data.get("country"),
        "gender": gender,
        "last_seen_online_at": getattr(bot, "last_seen_online_at", None),
        "last_recording_ended_at": getattr(bot, "last_recording_ended_at", None),
        "updated_at": now,
    }
    if row is None:
        row = StreamerRow(username=username, site=site, **fields)
        session.add(row)
        session.flush()
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    return row


def sync_streamers_from_bots(bots: list[Bot]) -> None:
    try:
        with session_scope() as session:
            for bot in bots:
                upsert_streamer_row(session, bot)
    except Exception:
        logger.exception("Failed to sync streamers to database")


def recording_started(bot: Bot, abs_file_path: str) -> int | None:
    try:
        with session_scope() as session:
            streamer = upsert_streamer_row(session, bot)
            rec = RecordingRow(
                streamer_id=streamer.id,
                file_path=_relative_download_path(abs_file_path),
                started_at=datetime.now(timezone.utc),
                status="in_progress",
            )
            session.add(rec)
            session.flush()
            return int(rec.id)
    except Exception:
        logger.exception("recording_started failed")
        return None


def recording_finished(
    recording_id: int | None,
    *,
    completed: bool,
    error_message: str | None = None,
    abs_path: str | None = None,
) -> None:
    if recording_id is None:
        return
    try:
        with session_scope() as session:
            rec = session.get(RecordingRow, recording_id)
            if rec is None:
                return
            rec.ended_at = datetime.now(timezone.utc)
            if completed:
                rec.status = "completed"
                if abs_path and os.path.isfile(abs_path):
                    rec.file_size_bytes = os.path.getsize(abs_path)
            else:
                rec.status = "error"
                if error_message:
                    rec.error_message = error_message[:8192]
    except Exception:
        logger.exception("recording_finished failed")


def record_status_event(bot: Bot) -> None:
    try:
        with session_scope() as session:
            streamer = upsert_streamer_row(session, bot)
            ev = StatusEventRow(
                streamer_id=streamer.id,
                at=datetime.now(timezone.utc),
                status_code=int(bot.sc.value),
                recording=bool(bot.recording),
            )
            session.add(ev)
    except Exception:
        logger.exception("record_status_event failed")
