"""Database layer — Postgres via SQLAlchemy.

Replaces the old single-user JSON file with real per-user storage so
multiple accounts can use the same deployment without colliding. Everything
here is plumbing (engine, session, ORM tables); the actual coach logic still
only knows about the plain :mod:`coach.store` dataclasses.
"""

from __future__ import annotations

import os
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    roadmap_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created: Mapped[date] = mapped_column(Date, default=date.today)

    records: Mapped[list["ProblemRecordRow"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    starred: Mapped[list["StarredRow"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProblemRecordRow(Base):
    __tablename__ = "problem_records"
    __table_args__ = (UniqueConstraint("user_id", "title", name="uq_user_problem"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(100))
    next_review: Mapped[date | None] = mapped_column(Date, nullable=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    review_streak: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="records")
    attempts: Mapped[list["AttemptRow"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", order_by="AttemptRow.seq"
    )


class AttemptRow(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("problem_records.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(40))
    used_hint: Mapped[bool] = mapped_column(Boolean, default=False)
    viewed_solution: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    seq: Mapped[int] = mapped_column(Integer, default=0)

    record: Mapped[ProblemRecordRow] = relationship(back_populates="attempts")


class StarredRow(Base):
    __tablename__ = "starred"
    __table_args__ = (UniqueConstraint("user_id", "title", name="uq_user_star"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))

    user: Mapped[User] = relationship(back_populates="starred")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env, e.g.\n"
            "    DATABASE_URL=postgresql+psycopg://coach:coach@localhost:5432/leetcode_coach"
        )
    return url


_engine = None
_SessionLocal = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), future=True)
    return _engine


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(engine())


def new_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine(), expire_on_commit=False, future=True)
    return _SessionLocal()
