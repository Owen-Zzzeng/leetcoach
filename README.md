# AI Daily LeetCode Coach

An AI coach that decides exactly what you should practice each day. Not a
tracker, not a dashboard — a coach. You only ever do two things:

1. Tell it how much time you have today.
2. Tell it (in plain English) how the session went.

The AI owns everything else: where you are on the roadmap, what to introduce
next, what to review, and when each problem should come back.

See [VISION.md](VISION.md) for the long-term product vision and how today's MVP
maps to it.

```
$ leetcode-coach plan 45

Today's a mix: two fresh Arrays & Hashing problems plus a quick review of
Two Sum to keep it warm.

Focus: a mix of new & review

  1. Two Sum  [review]
     Arrays & Hashing · Easy · ~8 min
     You solved this last week — a fast refresh before building on it.
  2. Group Anagrams  [new]
     Arrays & Hashing · Medium · ~22 min
     Next in your roadmap; builds directly on hashing patterns.
  ...

$ leetcode-coach done "Group Anagrams took me 25 min, needed one hint on the
  sorting key. Two Sum was instant."

Recorded:
  ✓ Group Anagrams  (solved with hints)   → review around 2026-07-14
  ✓ Two Sum  (reviewed easily)            → review around 2026-08-16

Nice — the hint on Group Anagrams was just the key-choice; the pattern itself
clearly landed. I'll surface it again in a couple of days to lock it in.
```

## How it works

- **Curriculum** — a fixed roadmap (NeetCode 150 in the MVP): topic order and
  candidate problems. The coach always knows where you are and what's next.
- **Scheduler** — Claude decides your daily plan from your history and today's
  available time, balancing new material against due reviews.
- **Memory** — every attempt, outcome, hint, and review date is stored as plain
  JSON and updated automatically from your natural-language feedback. You never
  edit it by hand.

The intelligence (planning + reading your feedback) runs through Claude with
structured outputs; the record it maintains is clean JSON so future features
(analytics, dashboards, custom roadmaps) build on the same foundation.

## How the coach reasons

"An AI decides" can sound like a black box, so here's exactly what happens
when you run `plan`.

**What's fixed math, and what's judgment.** Two very different things are
happening under the hood, and it's worth keeping them separate:

- *When a solved problem should come back for review* is **not** decided by
  the model. It's a deterministic spaced-repetition schedule (a light
  SM-2-style ladder — 1, 3, 7, 16, 35, 90 days), computed the same way every
  time in [`coach/review.py`](coach/review.py). This is the part that has to
  be predictable, so it isn't left to an LLM.
- *What to actually put in today's plan* — which of the due reviews are worth
  including, whether today leans toward new material or reinforcement, how
  much time each problem realistically needs — **is** Claude's judgment call,
  made fresh every time from your real history.

**What Claude actually sees.** Nothing is inferred from vibes — every
recommendation is grounded in a specific JSON payload built from your stored
history. For every problem you've touched, it gets:

| Signal | What it captures |
|---|---|
| `attempts` | how many times you've done this problem |
| `last_outcome` | solved independently / with hints / viewed solution / gave up / reviewed easily / struggled |
| `last_note` | your own words from the last recap (e.g. *"needed a hint to solve"*) |
| `days_overdue` | how far past (or before) its scheduled review date today is |
| `review_streak` | how many reviews in a row it's survived cleanly — a proxy for how solid it actually is |

...plus your full roadmap position (topic order, difficulty, what's still
new) and how many minutes you have today. No formula pre-computes a
"priority score" from these — the raw signals are handed over as-is, and
Claude weighs them the way a human coach would, in plain reasoning, not a
hardcoded rule.

**A real example.** Here's an actual `plan` run. `Top K Frequent Elements`
had `due_for_review: false` (its official review date was still a day out) —
a naive rule that only checks that flag would have skipped it. Claude
included it anyway:

> You struggled and needed a hint last time and it's still unsolved —
> reinforcing it now before moving on will make it stick.

It looked past the due-date flag to `review_streak: 0` and `last_outcome:
struggled` and judged the forgetting risk was already high enough to act on
today. That's the difference between a scheduler that follows a flag and a
coach that reads the whole picture.

**Guardrails.** The response is constrained to a fixed JSON schema
(`output_config`), so the *shape* of the plan can never come back malformed —
only the *content* (which problems, in what order, for what reason) is the
model's call. If a returned title doesn't match a real roadmap problem, the
app silently drops it rather than trusting it blind
([`coach/coach.py`](coach/coach.py)).

## Install

```bash
pip install -e .
```

Set your Anthropic API key (or use the `ant` CLI login):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Use

```bash
leetcode-coach init            # choose a roadmap (once)
leetcode-coach plan 45         # "I have 45 minutes" -> today's plan
leetcode-coach done "..."      # recap your session in plain English
leetcode-coach progress        # a quick look at where you are
```

`plan` accepts natural phrasings too: `plan "1 hour"`, `plan 90m`.

If you don't want to install, run it as a module: `python -m coach plan 45`.

Your history lives at `~/.leetcode-coach/state.json` (override with
`LEETCODE_COACH_HOME` or `--state`).

## Web app

There's also a chat-style web front end ([`web/`](web/)) over the same coach
logic, with email/password accounts so multiple people can use one
deployment without seeing each other's history. It needs Postgres, not the
CLI's JSON file:

```bash
docker compose up -d          # starts Postgres on localhost:5433
```

Add to `.env` (see [`.env.example`](.env.example)):

```
DATABASE_URL=postgresql+psycopg://coach:coach@localhost:5433/leetcode_coach
```

Then:

```bash
leetcode-coach-web            # creates tables on first run, serves on :5057
```

Open `http://localhost:5057` — it'll ask you to register/log in before
showing the app. Each account gets its own roadmap progress, review
schedule, and starred problems (`coach/db.py`, `coach/db_store.py`,
`coach/auth.py`). The CLI is unaffected — it's still single-user, local,
JSON-file-backed, no login.

## Roadmap (beyond the MVP)

The architecture is built to grow into the full vision without a redesign:
personalized mistake analysis, concept-level mastery, adaptive spaced
repetition, interview-deadline plans, multiple/custom roadmaps, and a richer
dashboard. All of it builds on the same core idea — the AI observes your
history, knows where you are, and decides what you practice next.
