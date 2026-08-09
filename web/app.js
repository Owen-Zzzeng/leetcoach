// Tiny chat front end for the coach. No framework, no build step.
//
// Conversation state machine:
//   "minutes"  -> waiting for "how many minutes today?" answer
//   "feedback" -> plan has been shown; waiting for the post-session recap
//
// The two states map 1:1 onto the two endpoints: POST /api/plan and
// POST /api/done.

const chat = document.getElementById("chat");
const composer = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const tabs = document.getElementById("tabs");
const calendarView = document.getElementById("calendarView");
const calendarGrid = document.getElementById("calendarGrid");
const monthLabel = document.getElementById("monthLabel");
const prevMonthBtn = document.getElementById("prevMonth");
const nextMonthBtn = document.getElementById("nextMonth");
const roadmapView = document.getElementById("roadmapView");
const logoutBtn = document.getElementById("logoutBtn");

logoutBtn.addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/";
});
const roadmapCrumb = document.getElementById("roadmapCrumb");
const roadmapTopics = document.getElementById("roadmapTopics");
const roadmapTableWrap = document.getElementById("roadmapTableWrap");
const roadmapTableBody = document.getElementById("roadmapTableBody");

let state = "minutes";
let busy = false;

function el(tag, className, children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (children != null) {
    (Array.isArray(children) ? children : [children]).forEach((c) => {
      if (c == null) return;
      node.append(typeof c === "string" ? document.createTextNode(c) : c);
    });
  }
  return node;
}

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

function addUserMessage(text) {
  const msg = el("div", "msg msg--user", el("div", "bubble", text));
  chat.append(msg);
  scrollToBottom();
}

function addCoachNode(node, opts = {}) {
  const bubble = el("div", "bubble" + (opts.error ? " bubble--error" : ""), node);
  const msg = el("div", "msg msg--coach", bubble);
  chat.append(msg);
  scrollToBottom();
  return msg;
}

function addCoachText(text, opts = {}) {
  return addCoachNode(text, opts);
}

function addTyping() {
  const dots = el("span", "typing", [el("span"), el("span"), el("span")]);
  return addCoachNode(dots);
}

// ---- rendering plan / recap payloads into cards ---------------------------

const FOCUS_LABEL = {
  new: "new material",
  review: "review",
  balanced: "a mix of new & review",
};

function renderPlan(plan) {
  const wrap = el("div", "plan");

  if (plan.coach_note) {
    wrap.append(el("div", "plan__note", plan.coach_note));
  }

  if (!plan.items || plan.items.length === 0) {
    wrap.append(el("div", "plan__note", "Nothing to practice right now — enjoy the break."));
    return wrap;
  }

  wrap.append(el("div", "plan__focus", "Focus: " + (FOCUS_LABEL[plan.focus] || plan.focus)));

  const items = el("div", "plan__items");
  plan.items.forEach((item, i) => {
    const tag = el(
      "span",
      "item__tag " + (item.kind === "review" ? "item__tag--review" : "item__tag--new"),
      item.kind
    );
    const top = el("div", "item__top", [
      el("span", "item__title", `${i + 1}. ${item.title}`),
      tag,
    ]);
    const meta = el(
      "div",
      "item__meta",
      `${item.topic} · ${item.difficulty} · ~${item.estimated_minutes} min`
    );
    const card = el("div", "item", [top, meta]);
    if (item.reason) card.append(el("div", "item__reason", item.reason));
    items.append(card);
  });
  wrap.append(items);
  wrap.append(el("div", "plan__total", `Estimated total: ~${plan.total_minutes} min`));

  return wrap;
}

function renderRecap(result) {
  const wrap = el("div", "recap");
  const applied = result.applied || [];

  applied.forEach((a) => {
    const outcome = a.outcome.replaceAll("_", " ");
    const row = el("div", "recap__row", [
      el("span", "recap__check", "✓"),
      el("span", null, a.title),
      el("span", "recap__outcome", `(${outcome})`),
    ]);
    wrap.append(row);
    if (a.next_review) {
      wrap.append(el("div", "recap__next", `→ review around ${a.next_review}`));
    }
  });

  if (result.coach_note) {
    wrap.append(el("div", "recap__note", result.coach_note));
  }

  const unmatched = result.unmatched || [];
  if (unmatched.length) {
    wrap.append(
      el("div", "recap__unmatched", "Couldn't match: " + unmatched.join(", "))
    );
  }

  if (!applied.length && !unmatched.length && !result.coach_note) {
    wrap.append(el("div", null, "Nothing recorded from that."));
  }

  return wrap;
}

// ---- API calls --------------------------------------------------------- //

async function callApi(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || "Something went wrong.");
  }
  return data;
}

function parseMinutes(text) {
  const hourMatch = text.match(/(\d+)\s*(?:h|hour|hours)/i);
  const minMatch = text.match(/(\d+)\s*(?:m|min|mins|minute|minutes)/i);
  let total = 0;
  if (hourMatch) total += parseInt(hourMatch[1], 10) * 60;
  if (minMatch) total += parseInt(minMatch[1], 10);
  if (total) return total;
  const bare = text.match(/\d+/);
  return bare ? parseInt(bare[0], 10) : null;
}

// ---- conversation flow --------------------------------------------------- //

const ONBOARDING_TEXT =
  "Quick intro: tell me how much time you have, I'll put together today's plan, " +
  "then once you're done just tell me how it went in your own words — no forms, " +
  "I'll figure out the rest.";

async function askForMinutes() {
  addCoachText(ONBOARDING_TEXT);

  const typing = addTyping();
  try {
    const res = await fetch("/api/greeting");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    typing.remove();
    addCoachText(data.message);
  } catch (err) {
    typing.remove();
    addCoachText("How many minutes do you want to practice today?");
  }
}

async function handleMinutes(text) {
  const minutes = parseMinutes(text);
  if (minutes == null || minutes <= 0) {
    addCoachText("I didn't catch a number — how many minutes do you have today?");
    return;
  }

  const typing = addTyping();
  busy = true;
  try {
    const plan = await callApi("/api/plan", { minutes });
    typing.remove();
    addCoachNode(renderPlan(plan));
    addCoachText("Go do those — when you're done, type `done` and tell me how it went.");
    state = "feedback";
  } catch (err) {
    typing.remove();
    addCoachText(err.message, { error: true });
  } finally {
    busy = false;
  }
}

async function handleFeedback(text) {
  const bare = text.trim().toLowerCase();
  if (bare === "done" || bare === "finished" || bare === "done.") {
    addCoachText("Tell me how each problem went, in your own words — solved it clean? needed a hint? gave up?");
    return; // stay in "feedback" state, wait for the real recap
  }

  const typing = addTyping();
  busy = true;
  try {
    const result = await callApi("/api/done", { feedback: text });
    typing.remove();
    addCoachNode(renderRecap(result));
    addCoachText("Nice work today! Whenever you're ready again — how many minutes do you have?");
    state = "minutes";
  } catch (err) {
    typing.remove();
    addCoachText(err.message, { error: true });
  } finally {
    busy = false;
  }
}

// ---- wiring --------------------------------------------------------- //

function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}

input.addEventListener("input", autoGrow);

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    composer.requestSubmit();
  }
});

composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (busy) return;

  const text = input.value.trim();
  if (!text) return;

  addUserMessage(text);
  input.value = "";
  autoGrow();

  if (state === "minutes") {
    await handleMinutes(text);
  } else {
    await handleFeedback(text);
  }
});

// ---- calendar view --------------------------------------------------- //

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const today = new Date();
let viewYear = today.getFullYear();
let viewMonth = today.getMonth(); // 0-based
let historyCache = null;

function isoDate(y, m, d) {
  return `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

async function fetchHistory() {
  const res = await fetch("/api/history");
  const data = await res.json().catch(() => ({ days: {} }));
  return data.days || {};
}

function renderCalendarGrid(days) {
  calendarGrid.innerHTML = "";
  monthLabel.textContent = `${MONTH_NAMES[viewMonth]} ${viewYear}`;

  const firstOfMonth = new Date(viewYear, viewMonth, 1);
  const startOffset = firstOfMonth.getDay(); // 0 = Sunday
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const daysInPrevMonth = new Date(viewYear, viewMonth, 0).getDate();

  const todayIso = isoDate(today.getFullYear(), today.getMonth(), today.getDate());

  const cells = [];

  // leading days from the previous month, greyed out
  for (let i = startOffset - 1; i >= 0; i--) {
    cells.push({ num: daysInPrevMonth - i, outside: true, iso: null });
  }
  // this month
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ num: d, outside: false, iso: isoDate(viewYear, viewMonth, d) });
  }
  // trailing days to complete the last week
  while (cells.length % 7 !== 0) {
    cells.push({ num: cells.length, outside: true, iso: null });
  }

  cells.forEach((cell) => {
    const dayEl = el("div", "day" + (cell.outside ? " day--outside" : ""));
    if (cell.iso === todayIso) dayEl.classList.add("day--today");

    if (!cell.outside) {
      dayEl.append(el("div", "day__num", String(cell.num)));
      const entries = days[cell.iso] || [];
      entries.forEach((entry) => {
        const bar = el("div", `day__bar day__bar--${entry.color}`, entry.title);
        bar.title = `${entry.title} — ${entry.outcome.replaceAll("_", " ")}`;
        dayEl.append(bar);
      });
    }
    calendarGrid.append(dayEl);
  });
}

async function openCalendar() {
  calendarView.querySelector(".calendar__nav").style.visibility = "hidden";
  monthLabel.textContent = "Loading…";
  historyCache = await fetchHistory();
  calendarView.querySelector(".calendar__nav").style.visibility = "visible";
  renderCalendarGrid(historyCache);
}

prevMonthBtn.addEventListener("click", () => {
  viewMonth -= 1;
  if (viewMonth < 0) {
    viewMonth = 11;
    viewYear -= 1;
  }
  renderCalendarGrid(historyCache || {});
});

nextMonthBtn.addEventListener("click", () => {
  viewMonth += 1;
  if (viewMonth > 11) {
    viewMonth = 0;
    viewYear += 1;
  }
  renderCalendarGrid(historyCache || {});
});

tabs.addEventListener("click", (e) => {
  const btn = e.target.closest(".tabs__btn");
  if (!btn) return;
  const tab = btn.dataset.tab;

  tabs.querySelectorAll(".tabs__btn").forEach((b) => b.classList.toggle("is-active", b === btn));

  chat.hidden = tab !== "chat";
  composer.hidden = tab !== "chat";
  calendarView.hidden = tab !== "calendar";
  roadmapView.hidden = tab !== "roadmap";

  if (tab === "calendar") {
    openCalendar();
  } else if (tab === "roadmap") {
    openRoadmap();
  }
});

// ---- roadmap view --------------------------------------------------- //

const DIFFICULTY_RANK = { Easy: 0, Medium: 1, Hard: 2 };

let roadmapCache = null;
let currentTopic = null; // topic name, or null when showing the topic grid
let sortKey = null; // "title" | "difficulty" | null (roadmap order)
let sortDir = 1;

async function fetchRoadmap() {
  const res = await fetch("/api/roadmap");
  const data = await res.json().catch(() => ({ topics: [] }));
  return data.topics || [];
}

function diffClass(difficulty) {
  return "diff diff--" + difficulty.toLowerCase();
}

function renderTopicGrid() {
  roadmapCrumb.innerHTML = "";
  roadmapTableWrap.hidden = true;
  roadmapTopics.hidden = false;
  roadmapTopics.innerHTML = "";

  roadmapCache.forEach((t) => {
    const pct = t.total ? Math.round((t.solved / t.total) * 100) : 0;
    const card = el("button", "topic-card", [
      el("div", "topic-card__name", t.topic),
      el("div", "topic-card__count", `${t.solved} / ${t.total} solved`),
      el("div", "topic-card__bar", el("div", "topic-card__bar-fill")),
    ]);
    card.querySelector(".topic-card__bar-fill").style.width = pct + "%";
    card.type = "button";
    card.addEventListener("click", () => openTopic(t.topic));
    roadmapTopics.append(card);
  });
}

function sortedProblems(problems) {
  if (!sortKey) return problems;
  const list = [...problems];
  list.sort((a, b) => {
    let cmp;
    if (sortKey === "difficulty") {
      cmp = DIFFICULTY_RANK[a.difficulty] - DIFFICULTY_RANK[b.difficulty];
    } else {
      cmp = a.title.localeCompare(b.title);
    }
    return cmp * sortDir;
  });
  return list;
}

async function toggleStar(title, starred, btn) {
  btn.classList.toggle("is-starred", starred);
  btn.textContent = starred ? "★" : "☆";
  try {
    await callApi("/api/star", { title, starred });
  } catch (err) {
    // revert on failure
    btn.classList.toggle("is-starred", !starred);
    btn.textContent = !starred ? "★" : "☆";
  }
  // keep the in-memory cache consistent so re-sorts / re-renders don't lose it
  const topic = roadmapCache.find((t) => t.topic === currentTopic);
  const prob = topic && topic.problems.find((p) => p.title === title);
  if (prob) prob.starred = starred;
}

function renderProblemTable() {
  const topic = roadmapCache.find((t) => t.topic === currentTopic);
  roadmapTopics.hidden = true;
  roadmapTableWrap.hidden = false;

  roadmapCrumb.innerHTML = "";
  const back = el("button", null, "‹ Topics");
  back.type = "button";
  back.addEventListener("click", () => {
    currentTopic = null;
    renderTopicGrid();
  });
  roadmapCrumb.append(back, ` / ${currentTopic} (${topic.solved}/${topic.total})`);

  document.querySelectorAll(".roadmap__table th.sortable .sort-arrow").forEach((a) => a.remove());
  if (sortKey) {
    const th = document.querySelector(`.roadmap__table th[data-sort="${sortKey}"]`);
    if (th) th.append(el("span", "sort-arrow", sortDir === 1 ? "↑" : "↓"));
  }

  roadmapTableBody.innerHTML = "";
  sortedProblems(topic.problems).forEach((p) => {
    const statusDot = el("span", "status-dot" + (p.solved ? " is-solved" : ""), p.solved ? "✓" : "");
    const starBtn = el("button", "star-btn" + (p.starred ? " is-starred" : ""), p.starred ? "★" : "☆");
    starBtn.type = "button";
    starBtn.addEventListener("click", () => toggleStar(p.title, !p.starred, starBtn));

    const row = el("tr", null, [
      el("td", "col-status", statusDot),
      el("td", "col-star", starBtn),
      el("td", "col-title", p.title),
      el("td", "col-diff", el("span", diffClass(p.difficulty), p.difficulty)),
    ]);
    roadmapTableBody.append(row);
  });
}

function openTopic(topicName) {
  currentTopic = topicName;
  sortKey = null;
  renderProblemTable();
}

async function openRoadmap() {
  if (!roadmapCache) {
    roadmapCrumb.textContent = "Loading…";
    roadmapCache = await fetchRoadmap();
  }
  if (currentTopic) {
    renderProblemTable();
  } else {
    renderTopicGrid();
  }
}

document.querySelector(".roadmap__table thead").addEventListener("click", (e) => {
  const th = e.target.closest("th.sortable");
  if (!th) return;
  const key = th.dataset.sort;
  if (sortKey === key) {
    sortDir *= -1;
  } else {
    sortKey = key;
    sortDir = 1;
  }
  renderProblemTable();
});

askForMinutes();
