"""Persistent learning history ("Memory").

The user never edits this by hand. The AI updates it from natural-language
feedback after each session. It is plain JSON so future features (dashboards,
knowledge graphs, analytics) can build on it without a redesign.

State lives at ``~/.leetcode-coach/state.json`` by default. Every problem the
user has interacted with gets a record; problems never touched simply have no
record yet (they are "new").
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any


def default_state_path() -> Path:
    override = os.environ.get("LEETCODE_COACH_HOME")
    base = Path(override) if override else Path.home() / ".leetcode-coach"
    return base / "state.json"


@dataclass
class Attempt:
    """One recorded practice session on a problem."""

    date: str  # ISO date, e.g. "2026-07-12"
    minutes: int | None = None
    # How it went, as classified by the AI from the user's words.
    # One of: "solved_independently", "solved_with_hints", "viewed_solution",
    # "gave_up", "reviewed_easily", "struggled".
    outcome: str = "solved_independently"
    used_hint: bool = False
    viewed_solution: bool = False
    notes: str = ""
    # Monotonically increasing across the whole state, in recording order.
    # Same-day attempts on different problems have no time-of-day, so this is
    # what lets the calendar view stack a day's problems in the order they
    # were actually recorded.
    seq: int = 0


@dataclass
class ProblemRecord:
    """Everything the coach remembers about one problem."""

    title: str
    topic: str
    attempts: list[Attempt] = field(default_factory=list)
    # When this problem should next surface for review (ISO date), or None if
    # no review is currently scheduled.
    next_review: str | None = None
    # Spaced-repetition interval in days used to compute the last next_review.
    interval_days: int = 0
    # Rolling count of successful reviews (drives interval growth).
    review_streak: int = 0

    @property
    def first_seen(self) -> str | None:
        return self.attempts[0].date if self.attempts else None

    @property
    def last_attempt(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    @property
    def solved(self) -> bool:
        """Has the user ever gotten this problem out (with or without help)?"""
        return any(
            a.outcome
            in ("solved_independently", "solved_with_hints", "reviewed_easily")
            for a in self.attempts
        )


@dataclass
class State:
    roadmap_id: str | None = None
    created: str = ""
    records: dict[str, ProblemRecord] = field(default_factory=dict)
    # Starred problems, independent of attempt history — a problem can be
    # starred before it's ever been attempted.
    starred: list[str] = field(default_factory=list)

    def record_for(self, title: str, topic: str) -> ProblemRecord:
        rec = self.records.get(title)
        if rec is None:
            rec = ProblemRecord(title=title, topic=topic)
            self.records[title] = rec
        return rec


class Store:
    """Loads and saves :class:`State` as JSON."""

    def __init__(self, path: Path | None = None):
        self.path = path or default_state_path()

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> State:
        if not self.path.exists():
            return State()
        raw = json.loads(self.path.read_text())
        records = {
            title: _record_from_dict(rec) for title, rec in raw.get("records", {}).items()
        }
        return State(
            roadmap_id=raw.get("roadmap_id"),
            created=raw.get("created", ""),
            records=records,
            starred=raw.get("starred", []),
        )

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "roadmap_id": state.roadmap_id,
            "created": state.created or date.today().isoformat(),
            "records": {title: asdict(rec) for title, rec in state.records.items()},
            "starred": sorted(state.starred),
        }
        # Write atomically so a crash mid-write can't corrupt history.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self.path)


def _record_from_dict(raw: dict[str, Any]) -> ProblemRecord:
    return ProblemRecord(
        title=raw["title"],
        topic=raw["topic"],
        attempts=[Attempt(**a) for a in raw.get("attempts", [])],
        next_review=raw.get("next_review"),
        interval_days=raw.get("interval_days", 0),
        review_streak=raw.get("review_streak", 0),
    )
