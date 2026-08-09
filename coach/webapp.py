"""Chat-style web front end over the same Coach logic the CLI uses.

Multi-user: each visitor registers/logs in with email + password
(``coach/auth.py``), and every API call below is scoped to
``session['user_id']`` via a per-user :class:`coach.db_store.DbStore` — so
concurrent accounts on the same deployment never see each other's history.
This is a separate storage backend from the CLI's JSON file; the CLI is
still single-user/local and untouched.
"""

from __future__ import annotations

import functools
import os
import secrets
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory, session

from . import auth, db, llm
from .coach import Coach, Plan
from .db_store import DbStore
from .roadmap import available_roadmaps

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Calendar color coding: how each recorded outcome maps to a traffic-light
# read on the day's practice, regardless of whether it was new material or a
# review — same three buckets either way (good / needed help / didn't get it).
_OUTCOME_COLOR = {
    "solved_independently": "green",
    "reviewed_easily": "green",
    "solved_with_hints": "yellow",
    "struggled": "yellow",
    "viewed_solution": "red",
    "gave_up": "red",
}


def _project_env_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent / ".env"
    return Path.cwd() / ".env"


def _secret_key() -> str:
    """A stable session-signing key. Generated once and persisted to .env so
    logged-in sessions survive a server restart in dev; set FLASK_SECRET_KEY
    yourself in production instead of relying on this."""
    key = os.environ.get("FLASK_SECRET_KEY")
    if key:
        return key
    key = secrets.token_hex(32)
    path = _project_env_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\nFLASK_SECRET_KEY={key}\n")
    return key


llm._load_dotenv()

app = Flask(__name__, static_folder=None)
app.secret_key = _secret_key()

# Per-user in-memory cache of "today's plan", used only so /api/done can
# match feedback against it. Ephemeral by design (resets on restart), same
# as the old single-user version — just keyed by user now.
_last_plan_by_user: dict[int, Plan] = {}


def get_db():
    if "db" not in g:
        g.db = db.new_session()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    session_obj = g.pop("db", None)
    if session_obj is not None:
        session_obj.close()


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Not logged in."}), 401
        return view(*args, **kwargs)

    return wrapped


def current_coach() -> Coach:
    store = DbStore(user_id=session["user_id"], session=get_db())
    coach = Coach(store=store)
    if not coach.is_initialized():
        roadmaps = available_roadmaps()
        if not roadmaps:
            raise RuntimeError("No roadmaps are bundled with this install.")
        coach.initialize(roadmaps[0])
    return coach


# --- static files + page gate --------------------------------------------- #


@app.get("/")
def index():
    if "user_id" not in session:
        return send_from_directory(WEB_DIR, "login.html")
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename: str):
    return send_from_directory(WEB_DIR, filename)


# --- auth ------------------------------------------------------------------ #


@app.get("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in."}), 401
    user = get_db().get(db.User, session["user_id"])
    return jsonify({"email": user.email})


@app.post("/api/register")
def api_register():
    body = request.get_json(silent=True) or {}
    try:
        user = auth.register(get_db(), body.get("email", ""), body.get("password", ""))
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 400
    session["user_id"] = user.id
    return jsonify({"email": user.email})


@app.post("/api/login")
def api_login():
    body = request.get_json(silent=True) or {}
    try:
        user = auth.authenticate(get_db(), body.get("email", ""), body.get("password", ""))
    except auth.AuthError as exc:
        return jsonify({"error": str(exc)}), 401
    session["user_id"] = user.id
    return jsonify({"email": user.email})


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# --- coach API (all require login) ----------------------------------------- #


@app.get("/api/greeting")
@login_required
def api_greeting():
    coach = current_coach()
    try:
        greeting = llm.generate_greeting(coach.progress())
    except llm.LLMError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(greeting)


@app.post("/api/plan")
@login_required
def api_plan():
    coach = current_coach()

    minutes = (request.get_json(silent=True) or {}).get("minutes")
    if not isinstance(minutes, int) or minutes <= 0:
        return jsonify({"error": "Give me a positive number of minutes."}), 400

    try:
        plan = coach.plan_today(minutes)
    except llm.LLMError as exc:
        return jsonify({"error": str(exc)}), 502

    _last_plan_by_user[session["user_id"]] = plan
    return jsonify(
        {
            "focus": plan.focus,
            "coach_note": plan.coach_note,
            "items": [
                {
                    "title": i.title,
                    "kind": i.kind,
                    "difficulty": i.difficulty,
                    "topic": i.topic,
                    "estimated_minutes": i.estimated_minutes,
                    "reason": i.reason,
                }
                for i in plan.items
            ],
            "total_minutes": plan.total_minutes,
        }
    )


@app.post("/api/done")
@login_required
def api_done():
    coach = current_coach()

    feedback = ((request.get_json(silent=True) or {}).get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "Tell me a bit about how it went."}), 400

    plan = _last_plan_by_user.get(session["user_id"])
    try:
        result = coach.record_feedback(feedback, plan=plan)
    except llm.LLMError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


@app.get("/api/history")
@login_required
def api_history():
    """All recorded attempts, grouped by date, for the calendar view."""
    coach = current_coach()
    state = coach.store.load()

    days: dict[str, list[dict]] = {}
    for record in state.records.values():
        for attempt in record.attempts:
            days.setdefault(attempt.date, []).append(
                {
                    "title": record.title,
                    "outcome": attempt.outcome,
                    "color": _OUTCOME_COLOR.get(attempt.outcome, "yellow"),
                    "minutes": attempt.minutes,
                    "notes": attempt.notes,
                    "seq": attempt.seq,
                }
            )

    for entries in days.values():
        entries.sort(key=lambda e: e["seq"])

    return jsonify({"days": days})


@app.get("/api/roadmap")
@login_required
def api_roadmap():
    coach = current_coach()
    return jsonify(coach.roadmap_overview())


@app.post("/api/star")
@login_required
def api_star():
    coach = current_coach()
    body = request.get_json(silent=True) or {}
    title = body.get("title")
    if not title:
        return jsonify({"error": "Missing title."}), 400
    try:
        coach.set_starred(title, bool(body.get("starred")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify({"ok": True})


def main() -> None:
    db.init_db()
    app.run(port=5057, debug=False)


if __name__ == "__main__":
    main()
