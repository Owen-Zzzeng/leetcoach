"""Claude-backed intelligence for the coach.

Two responsibilities, both delegated to the model so the *decisions* live in the
coach's judgement rather than in hardcoded rules:

  - :func:`generate_plan`  — given the user's history and available time, decide
    what to practice today (new + review problems).
  - :func:`parse_feedback` — given the user's plain-English recap, extract what
    happened to each problem so history can be updated automatically.

Both use the Anthropic Messages API with structured outputs (``output_config``)
so the returned JSON validates against a fixed schema. The model defaults to
``claude-opus-4-8``. Set ``ANTHROPIC_API_KEY`` (or run ``ant auth login``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MODEL = "claude-opus-4-8"


class LLMError(RuntimeError):
    """Raised when the model call fails or the SDK is missing."""


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (existing env wins).

    No third-party dependency — just enough parsing for simple `.env` files.
    Looks in the current directory and, failing that, the project root (the
    directory containing pyproject.toml, for when the CLI is run from elsewhere).
    """
    candidates = [Path.cwd() / ".env"]
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            candidates.append(parent / ".env")
            break

    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        break


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LLMError(
            "The 'anthropic' package is required. Install it with:\n"
            "    pip install anthropic"
        ) from exc
    _load_dotenv()
    try:
        return anthropic.Anthropic()
    except Exception as exc:  # pragma: no cover - environment dependent
        raise LLMError(
            "Could not initialise the Anthropic client. Set ANTHROPIC_API_KEY "
            "or run `ant auth login`.\n"
            f"Original error: {exc}"
        ) from exc


def _first_text(response: Any) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    raise LLMError("Model returned no text content.")


def _call_structured(system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
    client = _client()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        if type(exc).__name__ == "NotFoundError":
            raise LLMError(
                f"Model {MODEL!r} was not found for this account. "
                "Check your API access."
            ) from exc
        raise LLMError(f"Model request failed: {exc}") from exc

    if response.stop_reason == "refusal":
        raise LLMError("The model declined to respond to this request.")

    text = _first_text(response)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise LLMError(f"Model returned invalid JSON: {text[:200]}") from exc


# --------------------------------------------------------------------------- #
# Plan generation
# --------------------------------------------------------------------------- #

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "focus": {
            "type": "string",
            "description": "Whether today leans toward new material or review.",
            "enum": ["new", "review", "balanced"],
        },
        "coach_note": {
            "type": "string",
            "description": "One or two friendly sentences to the user about today's plan and why.",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Exact problem title from the roadmap."},
                    "kind": {"type": "string", "enum": ["new", "review"]},
                    "estimated_minutes": {"type": "integer"},
                    "reason": {
                        "type": "string",
                        "description": "Short reason this problem was chosen for today.",
                    },
                },
                "required": ["title", "kind", "estimated_minutes", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["focus", "coach_note", "items"],
    "additionalProperties": False,
}

_PLAN_SYSTEM = """You are an expert LeetCode coach. Each day you decide exactly \
what the user should practice, so they never have to think about it themselves.

You are given:
  - the user's roadmap (fixed topic order and candidate problems),
  - their full learning history (attempts, outcomes, review schedule),
  - how many minutes they have today,
  - today's date.

Produce a focused daily plan that fits the available time. Principles:
  - Respect the roadmap order: introduce new problems roughly in sequence, and \
do not introduce a topic's problems before the user has made progress on \
earlier topics.
  - Prioritise reviews that are due (next_review on or before today) — spaced \
repetition matters more than racing ahead.
  - Balance new learning against reinforcement based on the user's recent \
performance: if they have been struggling or have a review backlog, lean toward \
review; if they are solving smoothly, introduce more new material.
  - Only choose problems that exist in the roadmap, using their exact titles.
  - Estimate minutes realistically by difficulty and whether it's a review \
(reviews are faster). The sum should fit within the available time, leaving a \
little slack. It is fine to return fewer problems than could theoretically fit.
  - If almost no time is available, it is fine to schedule a single quick review.

Choose the smallest set of problems that makes today productive. Quality over quantity."""


def generate_plan(context: dict[str, Any]) -> dict[str, Any]:
    """Ask the model for today's plan. ``context`` is a JSON-serialisable dict."""
    user = (
        "Here is everything you need to plan today's session.\n\n"
        + json.dumps(context, indent=2)
        + "\n\nProduce the plan."
    )
    return _call_structured(_PLAN_SYSTEM, user, _PLAN_SCHEMA)


# --------------------------------------------------------------------------- #
# Feedback parsing
# --------------------------------------------------------------------------- #

_FEEDBACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Exact roadmap title of a problem the user reported on.",
                    },
                    "outcome": {
                        "type": "string",
                        "enum": [
                            "solved_independently",
                            "solved_with_hints",
                            "viewed_solution",
                            "gave_up",
                            "reviewed_easily",
                            "struggled",
                        ],
                        "description": "How the session went for this problem.",
                    },
                    "minutes": {
                        "type": ["integer", "null"],
                        "description": "Minutes spent, if mentioned; otherwise null.",
                    },
                    "used_hint": {"type": "boolean"},
                    "viewed_solution": {"type": "boolean"},
                    "notes": {
                        "type": "string",
                        "description": "Brief note capturing anything useful (a struggle, a concept, a mistake).",
                    },
                },
                "required": [
                    "title",
                    "outcome",
                    "minutes",
                    "used_hint",
                    "viewed_solution",
                    "notes",
                ],
                "additionalProperties": False,
            },
        },
        "coach_note": {
            "type": "string",
            "description": "One or two encouraging, specific sentences reacting to how the session went.",
        },
        "unmatched": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything the user mentioned that could not be matched to a roadmap problem.",
        },
    },
    "required": ["updates", "coach_note", "unmatched"],
    "additionalProperties": False,
}

_FEEDBACK_SYSTEM = """You are an expert LeetCode coach reading a user's free-form \
recap of a practice session. Extract, for each problem they mention, exactly what \
happened so their learning history can be updated automatically. The user never \
fills out forms — you infer everything from their words.

You are given the list of problems that were on today's plan (with exact titles) \
plus the roadmap of all valid problems. Rules:
  - Match each thing the user describes to the correct roadmap problem by its \
exact title. Prefer titles from today's plan, but a user may also mention a \
different problem they did.
  - If the user refers to today's session collectively ("all easy", "both done", \
"finished everything", "no problems") without naming individual titles, apply \
that to every problem in today's plan — do not treat it as unmatched just \
because no title was said explicitly. Only fall back to "unmatched" when there \
is no today's plan to apply it to, or the phrase can't reasonably refer to it.
  - Classify the outcome honestly:
      solved_independently — solved with no help
      solved_with_hints    — solved but used a hint / looked something up
      viewed_solution      — ended up reading the solution
      gave_up              — did not finish and did not read the solution
      reviewed_easily      — a review problem that was quick/easy
      struggled            — a review problem that was hard or slow
  - Set used_hint / viewed_solution to reflect what they said.
  - Fill minutes only if a duration is stated or clearly implied; otherwise null.
  - Keep notes short and specific (the concept they missed, the bug they hit).
  - If they mention something you cannot map to a roadmap problem, list the raw \
phrase in "unmatched" rather than guessing.
  - Do not invent problems that weren't mentioned."""


def parse_feedback(context: dict[str, Any]) -> dict[str, Any]:
    """Extract structured updates from the user's natural-language recap."""
    user = (
        "Today's plan and the roadmap:\n\n"
        + json.dumps(context["reference"], indent=2)
        + "\n\nThe user's recap of how it went:\n\n"
        + context["feedback"]
        + "\n\nExtract the structured updates."
    )
    return _call_structured(_FEEDBACK_SYSTEM, user, _FEEDBACK_SCHEMA)


# --------------------------------------------------------------------------- #
# Session opener
# --------------------------------------------------------------------------- #

_GREETING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": (
                "A short, warm opening message that reacts to the user's real "
                "progress (or welcomes a first-timer) and ends by asking how "
                "many minutes they have to practice today."
            ),
        },
    },
    "required": ["message"],
    "additionalProperties": False,
}

_GREETING_SYSTEM = """You are an expert LeetCode coach opening today's session. \
Write ONE short, warm message (1-3 sentences, plain prose, no markdown, no bullet \
points) that:
  - If the user has any solved or attempted problems, briefly and specifically \
acknowledges where they stand (e.g. a topic they're mid-way through, a review \
backlog, recent momentum) — grounded in the real numbers you're given, not \
generic cheerleading.
  - If they have nothing solved or attempted yet, give a brief, friendly welcome \
instead.
  - Always end by asking how many minutes they have to practice today, phrased \
naturally in your own words — do not instruct them on a specific input format."""


def generate_greeting(context: dict[str, Any]) -> dict[str, Any]:
    """Ask the model for a session-opening line grounded in real progress."""
    user = (
        "Here is the user's current progress on their roadmap:\n\n"
        + json.dumps(context, indent=2)
        + "\n\nWrite the opening message."
    )
    return _call_structured(_GREETING_SYSTEM, user, _GREETING_SCHEMA)
