const state = {
  data: null,
  stories: [],
  selected: null,
  search: "",
  stateFilter: "",
  topicFilter: ""
};

const els = {};

function text(value) {
  return String(value ?? "");
}

function formatDate(value) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return text(value);
  return date.toISOString().slice(0, 10);
}

function formatSourceMode(value) {
  if (value === "curated_official_cases") return "official cases";
  if (value === "collected") return "live collector";
  return "stories.json";
}

function create(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

function chip(value) {
  return create("span", "tc-chip", value);
}

function storySearchText(story) {
  return [
    story.title,
    story.topic,
    story.source,
    story.snippet,
    ...(story.where || []),
    ...(story.statutes || []),
    ...(story.sectors || []),
    ...(story.terms || [])
  ]
    .join(" ")
    .toLowerCase();
}

function filteredStories() {
  return state.stories.filter((story) => {
    const matchesSearch = !state.search || storySearchText(story).includes(state.search);
    const matchesState = !state.stateFilter || (story.where || []).includes(state.stateFilter);
    const matchesTopic = !state.topicFilter || story.topic === state.topicFilter || (story.terms || []).includes(state.topicFilter);
    return matchesSearch && matchesState && matchesTopic;
  });
}

function setFilterOptions() {
  const states = new Set();
  const topics = new Set();
  state.stories.forEach((story) => {
    (story.where || []).forEach((item) => states.add(item));
    if (story.topic) topics.add(story.topic);
    (story.terms || []).forEach((item) => topics.add(item));
  });

  [...states].sort().forEach((item) => {
    const option = create("option", "", item);
    option.value = item;
    els.stateFilter.append(option);
  });

  [...topics].sort().forEach((item) => {
    const option = create("option", "", item);
    option.value = item;
    els.topicFilter.append(option);
  });
}

function renderStoryCard(story) {
  const card = create("button", "tc-card story-card");
  card.type = "button";
  if (state.selected && state.selected.link === story.link) {
    card.classList.add("is-active");
  }

  const meta = create("div", "story-meta");
  (story.where || []).forEach((item) => meta.append(chip(item)));
  if (story.topic) meta.append(chip(story.topic));

  const title = create("h3", "", story.title || "Untitled story");
  const source = create("span", "tc-label", `${story.source || "Unknown"} - ${story.date || "unknown date"}`);
  const snippet = create("p", "", story.snippet || "No snippet available.");

  const tags = create("div", "story-tags");
  (story.sectors || []).slice(0, 3).forEach((item) => tags.append(chip(item)));
  (story.statutes || []).slice(0, 3).forEach((item) => tags.append(chip(item)));

  const score = create("div", "story-score");
  score.append(create("span", "tc-label", "lead score"));
  score.append(create("strong", "", story.score ?? 0));

  card.append(meta, title, source, snippet, tags, score);
  card.addEventListener("click", () => {
    state.selected = story;
    renderStories();
    renderSelectedStory();
  });
  return card;
}

function renderStories() {
  const stories = filteredStories();
  els.storiesGrid.replaceChildren();
  els.activeFilter.textContent = stories.length === state.stories.length ? "all evidence" : `${stories.length} filtered`;

  if (!stories.length) {
    const empty = create("div", "tc-card empty-state");
    empty.append(
      create("h2", "", state.data?.empty_state?.title || "No matching stories"),
      create("p", "", state.data?.empty_state?.body || "Adjust the filters or regenerate stories.json.")
    );
    els.storiesGrid.append(empty);
    return;
  }

  stories.forEach((story) => els.storiesGrid.append(renderStoryCard(story)));
}

function valueList(values, fallback) {
  const cleaned = values.filter(Boolean);
  return cleaned.length ? cleaned.join(", ") : fallback;
}

function inferLead(story) {
  const where = valueList(story.where || [], "Midwest");
  const sectors = valueList(story.sectors || [], "employer");
  const score = Number(story.score || 0);
  if (score >= 9) return `Prioritize ${where} ${sectors} leads with similar pay practices.`;
  return `Monitor ${where} ${sectors} leads for repeat wage-hour indicators.`;
}

function inferTheory(story) {
  const terms = (story.terms || []).filter((term) => term !== "FLSA");
  if (terms.length) return valueList(terms.slice(0, 4), "wage-hour signal");
  return story.topic || "wage-hour signal";
}

function inferWatchNext(story) {
  const text = `${story.title || ""} ${story.snippet || ""}`.toLowerCase();
  if (text.includes("child labor")) return "Track repeat operators, franchise networks, hazardous tasks, and minor-hour patterns.";
  if (text.includes("retaliation")) return "Watch for worker cooperation issues, injunction activity, and repeat retaliation claims.";
  if (text.includes("tip")) return "Watch tip-pool rules, tip-credit notices, and dual-job side work.";
  if (text.includes("overtime")) return "Watch payroll methods, bonus inclusion, off-the-clock work, and repeat overtime patterns.";
  return "Watch source updates, related employers, and local coverage that confirms a broader pattern.";
}

function detailRow(label, value) {
  const row = create("div", "detail-row");
  row.append(create("span", "tc-label", label), create("strong", "", value));
  return row;
}

function renderSelectedStory() {
  const story = state.selected || state.stories[0];
  els.selectedStory.replaceChildren();
  els.selectedStory.append(create("span", "tc-label", "Case detail"));

  if (!story) {
    els.selectedStory.append(
      create("h2", "", "No case selected"),
      create("p", "", "Run the collector to populate the case board with in-scope wage and hour story leads.")
    );
    return;
  }

  const meta = create("div", "detail-meta");
  [
    ["Where", valueList(story.where || [], "unknown")],
    ["Source", story.source || "unknown"],
    ["Date", story.date || "unknown"],
    ["Score", story.score ?? 0]
  ].forEach(([label, value]) => {
    meta.append(detailRow(label, value));
  });

  const analysis = create("div", "case-analysis");
  [
    ["Targeting lead", inferLead(story)],
    ["Wage theory", inferTheory(story)],
    ["Watch next", inferWatchNext(story)]
  ].forEach(([label, value]) => analysis.append(detailRow(label, value)));

  const link = create("a", "evidence-link", "open source");
  link.href = story.link || "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";

  els.selectedStory.append(
    create("h2", "", story.title || "Untitled story"),
    create("p", "", story.snippet || "No snippet available."),
    meta,
    analysis,
    link
  );
}

function topValues(values, limit = 3) {
  const counts = new Map();
  values.filter(Boolean).forEach((value) => counts.set(value, (counts.get(value) || 0) + 1));
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit)
    .map(([value]) => value);
}

function signalRow(label, value) {
  const item = create("div", "signal-row");
  item.append(create("span", "tc-label", label), create("strong", "", value));
  return item;
}

function renderSignals() {
  els.signalItems.replaceChildren();
  const stories = state.stories;
  if (!stories.length) {
    els.signalItems.append(create("p", "", "No case signals loaded."));
    return;
  }

  const states = [...new Set(stories.flatMap((story) => story.where || []))].sort();
  const sources = topValues(stories.map((story) => story.source));
  const sectors = topValues(stories.flatMap((story) => story.sectors || []));
  const theories = topValues(stories.flatMap((story) => story.terms || []).filter((term) => term !== "FLSA"));

  [
    ["cases", `${stories.length} active`],
    ["states", states.join(", ") || "none tagged"],
    ["source mix", sources.join(", ") || "unknown"],
    ["sectors", sectors.join(", ") || "unclassified"],
    ["theories", theories.join(", ") || "unclassified"]
  ].forEach(([label, value]) => {
    els.signalItems.append(signalRow(label, value));
  });
}

function renderStats() {
  els.storyCount.textContent = state.stories.length;
  els.windowDays.textContent = `${state.data?.window_days || 7} days`;
  els.generatedAt.textContent = formatDate(state.data?.generated_at);
  els.sourceMode.textContent = formatSourceMode(state.data?.source_mode);
}

function bindEvents() {
  els.searchInput.addEventListener("input", (event) => {
    state.search = event.target.value.trim().toLowerCase();
    renderStories();
  });
  els.stateFilter.addEventListener("change", (event) => {
    state.stateFilter = event.target.value;
    renderStories();
  });
  els.topicFilter.addEventListener("change", (event) => {
    state.topicFilter = event.target.value;
    renderStories();
  });
}

async function loadData() {
  const source = document.querySelector("[data-source]")?.dataset.source || "stories.json";
  const response = await fetch(source, { cache: "no-store" });
  if (!response.ok) throw new Error(`Unable to load ${source}`);
  return response.json();
}

async function init() {
  [
    "generatedAt",
    "storyCount",
    "windowDays",
    "sourceMode",
    "searchInput",
    "stateFilter",
    "topicFilter",
    "storiesGrid",
    "activeFilter",
    "selectedStory",
    "signalItems"
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });

  bindEvents();
  try {
    state.data = await loadData();
  } catch (error) {
    state.data = {
      generated_at: new Date().toISOString(),
      window_days: 7,
      stories: [],
      trends: [],
      watchlist: [],
      empty_state: {
        title: "No story data loaded",
        body: "stories.json is missing or unavailable. Run the pipeline site-data command and publish again."
      }
    };
  }
  state.stories = state.data.stories || [];
  state.selected = state.stories[0] || null;
  setFilterOptions();
  renderStats();
  renderStories();
  renderSelectedStory();
  renderSignals();
}

document.addEventListener("DOMContentLoaded", init);
