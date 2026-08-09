"""Per-user Postgres-backed store.

Same load()/save(State) shape as :class:`coach.store.Store` (the original
single-user JSON file store), so :class:`coach.coach.Coach` and
:mod:`coach.review` don't need to know or care which backend they're
talking to. This one is scoped to a single ``user_id`` so multiple accounts
on the same deployment never see each other's history — replaces the JSON
file for the web app; the CLI still uses the original file-based Store.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db
from .store import Attempt, ProblemRecord, State


class DbStore:
    def __init__(self, user_id: int, session: Session):
        self.user_id = user_id
        self.session = session

    def load(self) -> State:
        user = self.session.get(db.User, self.user_id)
        if user is None:
            return State()

        records: dict[str, ProblemRecord] = {}
        for row in user.records:
            records[row.title] = ProblemRecord(
                title=row.title,
                topic=row.topic,
                attempts=[
                    Attempt(
                        date=a.date.isoformat(),
                        minutes=a.minutes,
                        outcome=a.outcome,
                        used_hint=a.used_hint,
                        viewed_solution=a.viewed_solution,
                        notes=a.notes,
                        seq=a.seq,
                    )
                    for a in row.attempts
                ],
                next_review=row.next_review.isoformat() if row.next_review else None,
                interval_days=row.interval_days,
                review_streak=row.review_streak,
            )

        return State(
            roadmap_id=user.roadmap_id,
            created=user.created.isoformat() if user.created else "",
            records=records,
            starred=[s.title for s in user.starred],
        )

    def save(self, state: State) -> None:
        user = self.session.get(db.User, self.user_id)
        if user is None:
            raise RuntimeError(f"Unknown user_id {self.user_id!r}")

        user.roadmap_id = state.roadmap_id
        if state.created:
            user.created = date.fromisoformat(state.created)

        # Full-replace on every save, mirroring the old JSON store's
        # "rewrite everything" semantics. Simple and correct at this data
        # size (at most a few hundred rows per user).
        for row in list(user.records):
            self.session.delete(row)
        for row in list(user.starred):
            self.session.delete(row)
        self.session.flush()

        for rec in state.records.values():
            row = db.ProblemRecordRow(
                user_id=self.user_id,
                title=rec.title,
                topic=rec.topic,
                next_review=date.fromisoformat(rec.next_review) if rec.next_review else None,
                interval_days=rec.interval_days,
                review_streak=rec.review_streak,
            )
            row.attempts = [
                db.AttemptRow(
                    date=date.fromisoformat(a.date),
                    minutes=a.minutes,
                    outcome=a.outcome,
                    used_hint=a.used_hint,
                    viewed_solution=a.viewed_solution,
                    notes=a.notes,
                    seq=a.seq,
                )
                for a in rec.attempts
            ]
            self.session.add(row)

        for title in state.starred:
            self.session.add(db.StarredRow(user_id=self.user_id, title=title))

        self.session.commit()
