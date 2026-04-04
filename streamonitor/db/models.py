from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StreamerRow(Base):
    __tablename__ = "streamers"
    __table_args__ = (UniqueConstraint("username", "site", name="uq_streamers_username_site"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(512), nullable=False)
    site: Mapped[str] = mapped_column(String(128), nullable=False)
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    country: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recording_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    recordings: Mapped[list[RecordingRow]] = relationship(back_populates="streamer")
    status_events: Mapped[list[StatusEventRow]] = relationship(back_populates="streamer")


class RecordingRow(Base):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(ForeignKey("streamers.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    streamer: Mapped[StreamerRow] = relationship(back_populates="recordings")


class StatusEventRow(Base):
    __tablename__ = "status_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(ForeignKey("streamers.id"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    recording: Mapped[bool] = mapped_column(Boolean, nullable=False)

    streamer: Mapped[StreamerRow] = relationship(back_populates="status_events")
