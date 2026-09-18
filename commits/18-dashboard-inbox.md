# Commit 18 — feat: add the alert inbox to the dashboard

Reference implementation commit: `a45101ed2adcaf004bec00225d73b784a771241c`
Apply after: `Commit 17`

## Goal

Add the dashboard bell, unread badge, filterable alert inbox, acknowledgement actions, and bounded visibility-aware polling.

## Files

### `web/app.js`

Replace this file with the complete post-commit content below.

````javascript
const API = "/api/v1";
const state = {
  language: "",
  search: "",
  sort: "stars",
  period: "30",
  chartMode: "stars",
  smooth: localStorage.getItem("radar-smooth") === "1",
  logScale: false,
  compare: new Set(),
  alertView: "unread",
  alertKind: "",
  alertsOpen: false,
  bursts: [],
  activeBurst: false,
  selectedRepo: null,
  series: null,
  riserWindow: "7",
  velocityMap: new Map(),
  theme: localStorage.getItem("radar-theme") || "dark",
};
const el = (id) => document.getElementById(id);
const periodDays = () => (state.period === "all" ? 365 : Number(state.period));
const SMOOTH_WINDOW = 7;
const MAX_COMPARE = 5;
const COMPARE_MODES = {
  stars: "absolute",
  delta: "indexed",
  growth: "percent",
};
const COMPARE_LABELS = {
  absolute: "stars",
  indexed: "indexed to 100",
  percent: "growth since the start of the window",
};
/* ---------- helpers ---------- */
async function fetchJSON(path, signal) {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && body.detail) message = body.detail;
    } catch (_) {
      /* keep default message */
    }
    throw new Error(message);
  }
  return response.json();
}
async function sendJSON(path, method, body) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (payload && payload.detail) message = payload.detail;
    } catch (_) {
      /* keep default message */
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}
function toast(message, type = "") {
  const container = el("toasts");
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  container.appendChild(node);
  setTimeout(() => node.remove(), 5000);
}
function formatNumber(value) {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
}
function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}
function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
/* ---------- status badge ---------- */
async function refreshStatusBadge() {
  const badge = el("status-badge");
  try {
    const health = await fetchJSON("/health");
    badge.textContent = health.status === "ok" ? "● online" : "● degraded";
    badge.classList.toggle("ok", health.status === "ok");
  } catch (_) {
    badge.textContent = "● offline";
  }
}
/* ---------- alert inbox ---------- */
const ALERT_POLL_MS = 30000;
let alertEventsAbortController = null;
let alertPollTimer = null;
function alertKindLabel(kind) {
  return {
    burst_started: "Burst",
    velocity_above: "Velocity",
    stars_reached: "Milestone",
  }[kind] || kind;
}
function renderAlertSummary(payload) {
  const count = el("alert-count");
  count.textContent = String(payload.unread_events);
  count.hidden = payload.unread_events === 0;
  el("alerts-summary").textContent =
    `${payload.unread_events} unread · ${payload.active_rules} active rule(s)`;
  el("acknowledge-all").disabled = payload.unread_events === 0;
}
async function loadAlertSummary() {
  try {
    renderAlertSummary(await fetchJSON(`${API}/alerts/summary`));
  } catch (err) {
    if (state.alertsOpen) toast(`Alerts: ${err.message}`, "warn");
  }
}
function renderAlertEvents(payload) {
  const container = el("alert-events");
  if (!payload.items.length) {
    container.innerHTML =
      `<div class="empty">${state.alertView === "unread" ? "No unread alerts." : "No alert events yet."}</div>`;
    return;
  }
  container.innerHTML = payload.items
    .map((event) => {
      const read = Boolean(event.acknowledged_at);
      const delivery = event.delivery_status.replaceAll("_", " ");
      return `
        <article class="alert-event ${read ? "read" : "unread"}">
          <div class="alert-event-icon" aria-hidden="true">${
            event.kind === "burst_started"
              ? "⚡"
              : event.kind === "stars_reached"
                ? "★"
                : "↗"
          }</div>
          <div class="alert-event-body">
            <div class="alert-event-meta">
              <span class="alert-kind">${escapeHtml(alertKindLabel(event.kind))}</span>
              <time datetime="${escapeHtml(event.created_at)}">${escapeHtml(formatDate(event.created_at))}</time>
            </div>
            <strong>${escapeHtml(event.title)}</strong>
            <p>${escapeHtml(event.message)}</p>
            <div class="alert-event-footer">
              <button class="link-btn" data-repository="${escapeHtml(event.repository)}">
                ${escapeHtml(event.repository)}
              </button>
              <span class="delivery ${escapeHtml(event.delivery_status)}">${escapeHtml(delivery)}</span>
            </div>
          </div>
          ${
            read
              ? ""
              : `<button class="btn small alert-ack" data-event-id="${event.id}">Mark read</button>`
          }
        </article>`;
    })
    .join("");
}
async function loadAlertEvents() {
  if (!state.alertsOpen) return;
  if (alertEventsAbortController) alertEventsAbortController.abort();
  alertEventsAbortController = new AbortController();
  const params = new URLSearchParams({ limit: "50" });
  if (state.alertView === "unread") params.set("acknowledged", "false");
  if (state.alertKind) params.set("kind", state.alertKind);
  el("alert-events").innerHTML =
    '<div class="empty"><span class="spinner"></span> Loading alerts…</div>';
  try {
    const payload = await fetchJSON(
      `${API}/alerts/events?${params}`,
      alertEventsAbortController.signal,
    );
    renderAlertEvents(payload);
  } catch (err) {
    if (err.name === "AbortError") return;
    el("alert-events").innerHTML =
      `<div class="empty">Failed to load alerts.<div class="hint">${escapeHtml(err.message)}</div></div>`;
  }
}
function setAlertsOpen(open) {
  state.alertsOpen = open;
  el("alerts-panel").hidden = !open;
  el("alerts-toggle").setAttribute("aria-expanded", String(open));
  if (open) {
    loadAlertSummary();
    loadAlertEvents();
    el("alerts-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (alertEventsAbortController) {
    alertEventsAbortController.abort();
  }
}
async function acknowledgeAlert(eventId) {
  try {
    await sendJSON(`${API}/alerts/events/${eventId}`, "PATCH", {
      acknowledged: true,
    });
    await Promise.all([loadAlertSummary(), loadAlertEvents()]);
  } catch (err) {
    toast(err.message, "error");
  }
}
async function acknowledgeAllAlerts() {
  try {
    const result = await sendJSON(`${API}/alerts/events/acknowledge-all`, "POST");
    toast(`Marked ${result.acknowledged} alert(s) as read`);
    await Promise.all([loadAlertSummary(), loadAlertEvents()]);
  } catch (err) {
    toast(err.message, "error");
  }
}
function startAlertPolling() {
  clearInterval(alertPollTimer);
  loadAlertSummary();
  alertPollTimer = setInterval(loadAlertSummary, ALERT_POLL_MS);
}
function stopAlertPolling() {
  clearInterval(alertPollTimer);
  alertPollTimer = null;
}
/* ---------- repositories table ---------- */
function renderReposTable(payload) {
  const wrap = el("repos-table-wrap");
  if (!payload.items.length) {
    const filtered = state.language || state.search;
    if (filtered) {
      wrap.innerHTML =
        '<div class="empty">Nothing matches your filters.' +
        '<div class="hint">Try a different language or search term.</div></div>';
    } else {
      el("risers-section").style.display = "none";
      wrap.innerHTML =
        '<div class="empty">No repositories tracked yet.' +
        '<div class="hint">Run <code>radar top --save</code> on the server, then refresh.</div></div>';
      emptyChart("Select a repository to see its star history");
    }
    return;
  }
  el("risers-section").style.display = "";
  const arrow = (key) =>
    state.sort === key
      ? '<span class="arrow">↓</span>'
      : '<span class="arrow">↕</span>';
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th class="cmp-col" title="Pick two or more to compare">⇄</th>
        <th class="sortable" data-sort="name">Repository ${arrow("name")}</th>
        <th>Language</th>
        <th class="sortable num" data-sort="stars">Stars ${arrow("stars")}</th>
        <th class="num">Forks</th>
      </tr>
    </thead>
    <tbody>
      ${payload.items
        .map((repo) => {
          const vel = state.velocityMap.get(repo.full_name);
          const velBadge = vel
            ? `<span class="mini-velocity" title="${vel.stars_per_day} stars/day over ${state.riserWindow}d">+${vel.stars_per_day}/d</span>`
            : "";
          return `
        <tr class="repo-row" data-full-name="${escapeHtml(repo.full_name)}">
          <td class="cmp-col">
            <input type="checkbox" class="cmp-box"
              data-full-name="${escapeHtml(repo.full_name)}"
              ${state.compare.has(repo.full_name) ? "checked" : ""} />
          </td>
          <td>${escapeHtml(repo.full_name)} ${velBadge}</td>
          <td>${repo.language ? `<span class="lang-badge">${escapeHtml(repo.language)}</span>` : "—"}</td>
          <td class="num">${formatNumber(repo.stargazers_count)}</td>
          <td class="num">${formatNumber(repo.forks_count)}</td>
        </tr>`;
        })
        .join("")}
    </tbody>
  `;
  wrap.innerHTML = "";
  wrap.appendChild(table);
  table.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      state.sort = th.dataset.sort;
      loadRepos();
    });
  });
  table.querySelectorAll("tr.repo-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectRepo(row.dataset.fullName);
    });
  });
  table.querySelectorAll("input.cmp-box").forEach((box) => {
    box.addEventListener("click", (event) => event.stopPropagation());
    box.addEventListener("change", () => toggleCompare(box));
  });
}
function showTableSpinner() {
  el("repos-table-wrap").innerHTML =
    '<div class="empty"><span class="spinner"></span> Loading repositories…</div>';
}
let reposAbortController = null;
async function loadRepos() {
  if (reposAbortController) reposAbortController.abort();
  reposAbortController = new AbortController();
  const params = new URLSearchParams({ sort: state.sort, limit: "100" });
  if (state.language) params.set("language", state.language);
  if (state.search) params.set("q", state.search);
  showTableSpinner();
  try {
    const payload = await fetchJSON(
      `${API}/repos?${params}`,
      reposAbortController.signal,
    );
    renderReposTable(payload);
    if (
      state.selectedRepo &&
      payload.items.some((r) => r.full_name === state.selectedRepo)
    ) {
      selectRepo(state.selectedRepo);
    }
  } catch (err) {
    if (err.name === "AbortError") return;
    el("repos-table-wrap").innerHTML =
      `<div class="empty">Failed to load repositories.<div class="hint">${escapeHtml(err.message)}</div></div>`;
    toast(err.message, "error");
  }
}
/* ---------- repo detail + chart ---------- */
async function selectRepo(fullName) {
  state.selectedRepo = fullName;
  document.querySelectorAll("tr.repo-row").forEach((row) => {
    row.classList.toggle("selected", row.dataset.fullName === fullName);
  });
  el("chart-sub").textContent = `${fullName} — loading…`;
  try {
    const [detail, series, velocity, bursts] = await Promise.all([
      fetchJSON(`${API}/repos/${fullName}`),
      fetchJSON(
        `${API}/analytics/series/${fullName}?days=${periodDays()}&smooth=${SMOOTH_WINDOW}`,
      ),
      loadVelocity(fullName),
      loadBursts(fullName, periodDays()),
    ]);
    state.series = series;
    state.bursts = bursts ? bursts.items : [];
    state.activeBurst = bursts ? bursts.active_burst : false;
    renderChart();
    renderVelocityBadges(velocity);
    renderBurstStrip(bursts);
    renderChartSubtitle(fullName, detail.latest_snapshot);
  } catch (err) {
    state.series = null;
    state.bursts = [];
    state.activeBurst = false;
    el("chart-sub").textContent = `${fullName} — failed to load history`;
    toast(err.message, "error");
  }
}
function renderChartSubtitle(fullName, latest) {
  const parts = [fullName];
  if (latest) {
    parts.push(
      `${formatNumber(latest.stargazers_count)} stars, ${formatNumber(latest.forks_count)} forks`,
    );
  } else {
    parts.push("no data yet");
  }
  if (state.bursts.length) {
    parts.push(`${state.bursts.length} burst(s) in this window`);
  }
  const subtitle = el("chart-sub");
  subtitle.textContent = parts.join(" — ");
  if (state.activeBurst) {
    const badge = document.createElement("span");
    badge.className = "burst-badge";
    badge.textContent = "active burst";
    subtitle.append(" ", badge);
  }
}
/* ---------- comparison ---------- */
function toggleCompare(box) {
  const fullName = box.dataset.fullName;
  if (box.checked) {
    if (state.compare.size >= MAX_COMPARE) {
      box.checked = false;
      toast(`Compare up to ${MAX_COMPARE} repositories at once`, "warn");
      return;
    }
    state.compare.add(fullName);
  } else {
    state.compare.delete(fullName);
  }
  renderCompareBar();
  syncToolbar();
  renderChart();
}
function clearCompare() {
  state.compare.clear();
  document.querySelectorAll("input.cmp-box").forEach((box) => {
    box.checked = false;
  });
  renderCompareBar();
  syncToolbar();
  renderChart();
}
function renderCompareBar() {
  const bar = el("compare-bar");
  if (!state.compare.size) {
    bar.innerHTML = "";
    bar.style.display = "none";
    return;
  }
  bar.style.display = "";
  bar.innerHTML =
    [...state.compare]
      .map((name) => `<span class="chip">${escapeHtml(name)}</span>`)
      .join("") + '<button class="btn small" id="clear-compare">Clear</button>';
  el("clear-compare").addEventListener("click", clearCompare);
}
async function renderComparison() {
  const names = [...state.compare];
  const mode = COMPARE_MODES[state.chartMode];
  const params = new URLSearchParams({
    repos: names.join(","),
    window: String(periodDays()),
    mode,
  });
  el("chart-sub").textContent = `Comparing ${names.length} repositories…`;
  try {
    const payload = await fetchJSON(`${API}/analytics/compare?${params}`);
    renderCompareChart(payload.days, payload.series, payload.mode);
    el("chart-sub").textContent =
      `Comparing ${names.length} repositories — ${COMPARE_LABELS[mode]}, last ${payload.window_days} days`;
  } catch (err) {
    emptyChart("Failed to compare repositories");
    el("chart-sub").textContent = `Comparison failed — ${err.message}`;
    toast(err.message, "error");
  }
}
function renderChart() {
  if (state.compare.size >= 2) {
    renderComparison();
    return;
  }
  if (!state.selectedRepo) {
    emptyChart("Select a repository to see its star history");
    return;
  }
  const points = state.series ? state.series.points : [];
  renderSeriesChart(state.selectedRepo, points, {
    mode: state.chartMode,
    smooth: state.smooth,
    logScale: state.logScale,
    bursts: state.bursts,
  });
}
function setChartMode(mode) {
  state.chartMode = mode;
  document.querySelectorAll("#chart-mode button").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  syncToolbar();
  renderChart();
}
function syncToolbar() {
  const comparing = state.compare.size >= 2;
  const deltaButton = document.querySelector(
    '#chart-mode button[data-mode="delta"]',
  );
  deltaButton.textContent = comparing ? "Indexed" : "Daily Δ";
  const smoothToggle = el("smooth-toggle");
  const smoothable = !comparing && state.chartMode !== "growth";
  smoothToggle.disabled = !smoothable;
  smoothToggle.checked = state.smooth && smoothable;
  smoothToggle.closest(".toggle").classList.toggle("disabled", !smoothable);
  const logToggle = el("log-toggle");
  const loggable = !comparing && state.chartMode === "stars";
  logToggle.disabled = !loggable;
  logToggle.checked = state.logScale && loggable;
  logToggle.closest(".toggle").classList.toggle("disabled", !loggable);
}
/* ---------- velocity + bursts (best-effort, never break the chart) ---------- */
async function loadVelocity(fullName) {
  const [owner, name] = fullName.split("/");
  try {
    return await fetchJSON(
      `${API}/analytics/velocity/${encodeURIComponent(owner)}/${encodeURIComponent(name)}?windows=7,30,90`,
    );
  } catch (_) {
    return null;
  }
}
async function loadBursts(fullName, days = 90) {
  const [owner, name] = fullName.split("/");
  try {
    return await fetchJSON(
      `${API}/analytics/bursts/${encodeURIComponent(owner)}/${encodeURIComponent(name)}?days=${days}`,
    );
  } catch (_) {
    return null;
  }
}
function renderVelocityBadges(velocity) {
  const box = el("velocity-badges");
  if (!velocity || !velocity.velocities.length) {
    box.innerHTML = "";
    return;
  }
  const badges = velocity.velocities.map(
    (v) =>
      `<span class="badge badge-velocity">+${v.stars_per_day}/d · ${v.window_days}d</span>`,
  );
  if (velocity.trend) {
    const up = velocity.trend.slope >= 0;
    badges.push(
      `<span class="badge badge-trend" title="OLS slope per day, r² = ${velocity.trend.r_squared}">${up ? "↗" : "↘"} trend ${velocity.trend.slope}/d</span>`,
    );
  }
  box.innerHTML = badges.join("");
}
function renderBurstStrip(bursts) {
  const strip = el("burst-strip");
  if (!bursts) {
    strip.innerHTML = "";
    return;
  }
  const parts = [];
  if (bursts.active_burst) {
    parts.push('<span class="badge badge-burst">⚡ Burst active</span>');
  }
  if (bursts.items.length) {
    const end = Date.now();
    const start = end - periodDays() * 24 * 60 * 60 * 1000;
    const span = end - start;
    const segments = bursts.items
      .map((b) => {
        const left =
          Math.max(0, (new Date(b.start_day).getTime() - start) / span) * 100;
        const right =
          Math.min(1, (new Date(b.end_day).getTime() - start) / span) * 100;
        const width = Math.max(right - left, 1.2);
        return (
          `<span class="burst-segment" style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%" ` +
          `title="${b.start_day} → ${b.end_day}: +${b.total_gained} stars in ${b.duration_days}d (peak +${b.peak_delta}/day)"></span>`
        );
      })
      .join("");
    parts.push(
      `<span class="strip-label">Bursts · ${periodDays()}d</span><span class="strip-track">${segments}</span>`,
    );
  }
  strip.innerHTML = parts.join("");
}
/* ---------- period switcher ---------- */
function applyPeriod() {
  if (state.selectedRepo) selectRepo(state.selectedRepo);
}
/* ---------- language filter ---------- */
async function loadLanguages() {
  try {
    const languages = await fetchJSON(`${API}/languages`);
    const select = el("language-filter");
    select.innerHTML =
      '<option value="">All languages</option>' +
      languages
        .map(
          (lang) =>
            `<option value="${escapeHtml(lang.language)}">` +
            `${escapeHtml(lang.language)} (${lang.repository_count})</option>`,
        )
        .join("");
    if (state.language) select.value = state.language;
  } catch (err) {
    toast(`Languages: ${err.message}`, "warn");
  }
}
/* ---------- leaderboard ---------- */
async function loadRisers() {
  const grid = el("riser-grid");
  const params = new URLSearchParams({
    window: state.riserWindow,
    limit: "100",
  });
  if (state.language) params.set("language", state.language);
  try {
    const payload = await fetchJSON(`${API}/analytics/leaderboard?${params}`);
    state.velocityMap = new Map(
      payload.items.map((item) => [item.full_name, item]),
    );
    const risers = payload.items.slice(0, 8);
    if (!risers.length) {
      grid.innerHTML =
        '<div class="empty">Not enough data yet — run <code>radar snapshot</code> for a few days.</div>';
      return;
    }
    const fastest = Math.max(...risers.map((repo) => repo.stars_per_day));
    grid.innerHTML = risers
      .map((repo) => {
        const share = fastest
          ? Math.round((repo.stars_per_day / fastest) * 100)
          : 0;
        return `
        <div class="riser-card" data-full-name="${escapeHtml(repo.full_name)}">
          <div class="rank">#${repo.rank}</div>
          <div class="name">${escapeHtml(repo.full_name)}</div>
          <div class="delta">+${formatNumber(repo.stars_per_day)} stars/day</div>
          <div class="sub">+${formatNumber(repo.stars_gained)} in ${state.riserWindow}d · ★ ${formatNumber(repo.stars)}</div>
          <div class="bar"><div class="bar-fill" style="width:${share}%"></div></div>
        </div>`;
      })
      .join("");
    grid.querySelectorAll(".riser-card").forEach((card) => {
      card.addEventListener("click", () => {
        state.search = "";
        el("search").value = "";
        selectRepo(card.dataset.fullName);
        loadRepos();
      });
    });
  } catch (err) {
    state.velocityMap.clear();
    grid.innerHTML = `<div class="empty">Failed to load risers.<div class="hint">${escapeHtml(err.message)}</div></div>`;
    toast(err.message, "error");
  }
}
function loadLeaderboardAndRepos() {
  return loadRisers().finally(loadRepos);
}
/* ---------- theme ---------- */
function applyTheme() {
  document.body.classList.toggle("light", state.theme === "light");
  el("theme-toggle").textContent = state.theme === "light" ? "☀️" : "🌙";
  localStorage.setItem("radar-theme", state.theme);
}
function toggleTheme() {
  state.theme = state.theme === "light" ? "dark" : "light";
  applyTheme();
  refreshChartColors();
  renderChart();
}
/* ---------- init ---------- */
function init() {
  applyTheme();
  renderCompareBar();
  syncToolbar();
  el("alerts-toggle").addEventListener("click", () => {
    setAlertsOpen(!state.alertsOpen);
  });
  el("alerts-close").addEventListener("click", () => setAlertsOpen(false));
  el("acknowledge-all").addEventListener("click", acknowledgeAllAlerts);
  el("alert-view").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    state.alertView = button.dataset.view;
    el("alert-view")
      .querySelectorAll("button")
      .forEach((item) => item.classList.toggle("active", item === button));
    loadAlertEvents();
  });
  el("alert-kind-filter").addEventListener("change", (event) => {
    state.alertKind = event.target.value;
    loadAlertEvents();
  });
  el("alert-events").addEventListener("click", (event) => {
    const acknowledge = event.target.closest("button[data-event-id]");
    if (acknowledge) {
      acknowledgeAlert(acknowledge.dataset.eventId);
      return;
    }
    const repository = event.target.closest("button[data-repository]");
    if (repository) {
      state.search = "";
      el("search").value = "";
      setAlertsOpen(false);
      selectRepo(repository.dataset.repository);
      loadRepos();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAlertPolling();
    else startAlertPolling();
  });
  el("language-filter").addEventListener("change", (event) => {
    state.language = event.target.value;
    loadLeaderboardAndRepos();
  });
  el("period-select").addEventListener("change", (event) => {
    state.period = event.target.value;
    applyPeriod();
  });
  el("smooth-toggle").addEventListener("change", (event) => {
    state.smooth = event.target.checked;
    localStorage.setItem("radar-smooth", state.smooth ? "1" : "0");
    renderChart();
  });
  el("log-toggle").addEventListener("change", (event) => {
    state.logScale = event.target.checked;
    renderChart();
  });
  el("reset-zoom").addEventListener("click", resetZoom);
  el("export-png").addEventListener("click", () => {
    const subject =
      state.compare.size >= 2
        ? `compare-${state.compare.size}`
        : state.selectedRepo;
    if (!subject) {
      toast("Select a repository first", "warn");
      return;
    }
    const stamp = new Date().toISOString().slice(0, 10);
    exportChartPng(
      `radar-${subject.replace("/", "-")}-${state.chartMode}-${stamp}.png`,
    );
  });
  el("chart-mode").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (!button || button.disabled) return;
    setChartMode(button.dataset.mode);
  });
  el("riser-window").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-window]");
    if (!button) return;
    state.riserWindow = button.dataset.window;
    document.querySelectorAll("#riser-window button").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    loadLeaderboardAndRepos();
  });
  let debounceTimer = null;
  el("theme-toggle").addEventListener("click", toggleTheme);
  el("search").addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(loadRepos, 300);
  });
  el("refresh-btn").addEventListener("click", () => {
    loadLeaderboardAndRepos();
    loadAlertSummary();
  });
  refreshChartColors();
  refreshStatusBadge();
  loadLanguages();
  loadLeaderboardAndRepos();
  startAlertPolling();
}
document.addEventListener("DOMContentLoaded", init);
````

### `web/index.html`

Replace this file with the complete post-commit content below.

````html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta
      name="description"
      content="Track star growth and spot rising stars on GitHub before everyone else."
    />
    <meta property="og:title" content="GitHub Radar" />
    <meta
      property="og:description"
      content="Find rising stars on GitHub — star growth charts, trending repositories, breakout detection."
    />
    <meta property="og:type" content="website" />
    <title>GitHub Radar — rising stars tracker</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <header class="topbar">
      <div class="brand">
        <svg
          class="logo"
          viewBox="0 0 24 24"
          width="28"
          height="28"
          aria-hidden="true"
        >
          <circle
            cx="12"
            cy="12"
            r="10"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
          />
          <circle
            cx="12"
            cy="12"
            r="5"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
          />
          <circle cx="12" cy="3" r="2" fill="currentColor" />
          <circle cx="19" cy="15" r="2" fill="currentColor" />
        </svg>
        <h1>GitHub Radar</h1>
      </div>
      <div class="topbar-actions">
        <button
          id="alerts-toggle"
          class="icon-btn alert-bell"
          title="Open alerts"
          aria-label="Open alerts"
          aria-expanded="false"
        >
          🔔
          <span id="alert-count" class="alert-count" hidden>0</span>
        </button>
        <button
          id="theme-toggle"
          class="icon-btn"
          title="Toggle theme"
          aria-label="Toggle theme"
        >
          🌙
        </button>
        <span class="status-badge" id="status-badge">loading…</span>
      </div>
    </header>
    <main class="content">
      <section class="filters card">
        <input
          id="search"
          type="search"
          placeholder="Search repositories…"
          autocomplete="off"
        />
        <select id="language-filter" aria-label="Filter by language">
          <option value="">All languages</option>
        </select>
        <select id="period-select" aria-label="Chart period">
          <option value="7">Last 7 days</option>
          <option value="30" selected>Last 30 days</option>
          <option value="90">Last 90 days</option>
          <option value="all">All time</option>
        </select>
        <button id="refresh-btn" class="btn">Refresh</button>
      </section>
      <section class="card alerts-panel" id="alerts-panel" hidden>
        <div class="alerts-head">
          <div>
            <h2>Alert inbox</h2>
            <p id="alerts-summary">Loading alert status…</p>
          </div>
          <div class="alerts-actions">
            <button id="acknowledge-all" class="btn small">Mark all read</button>
            <button
              id="alerts-close"
              class="icon-btn"
              aria-label="Close alerts"
              title="Close alerts"
            >
              ×
            </button>
          </div>
        </div>
        <div class="alerts-filters">
          <div class="seg" id="alert-view" role="group" aria-label="Alert status">
            <button class="active" data-view="unread">Unread</button>
            <button data-view="all">All</button>
          </div>
          <select id="alert-kind-filter" aria-label="Filter alerts by type">
            <option value="">All alert types</option>
            <option value="burst_started">Bursts</option>
            <option value="velocity_above">Velocity</option>
            <option value="stars_reached">Milestones</option>
          </select>
        </div>
        <div id="alert-events" class="alert-events">
          <div class="empty">Loading alerts…</div>
        </div>
      </section>
      <section class="grid">
        <div class="card">
          <h2>Tracked repositories</h2>
          <div class="table-wrap" id="repos-table-wrap">
            <div class="empty">Loading…</div>
          </div>
        </div>
        <div class="card chart-panel">
          <div class="chart-head">
            <div>
              <div class="chart-title">Star growth</div>
              <div class="chart-sub" id="chart-sub">
                Select a repository to see its history
              </div>
              <div class="badges-row" id="velocity-badges"></div>
              <div class="burst-strip-row" id="burst-strip"></div>
            </div>
            <div class="chart-toolbar">
              <div
                class="seg"
                id="chart-mode"
                role="group"
                aria-label="Chart mode"
              >
                <button class="active" data-mode="stars">Stars</button>
                <button data-mode="delta">Daily Δ</button>
                <button data-mode="growth">Growth %</button>
              </div>
              <label class="toggle">
                <input type="checkbox" id="smooth-toggle" />
                <span>SMA 7</span>
              </label>
              <label class="toggle">
                <input type="checkbox" id="log-toggle" />
                <span>Log scale</span>
              </label>
              <button id="reset-zoom" class="btn small">Reset zoom</button>
              <button id="export-png" class="btn small" title="Save as PNG">
                PNG
              </button>
            </div>
          </div>
          <div class="compare-bar" id="compare-bar" style="display: none"></div>
          <div id="chart"></div>
        </div>
        <section class="card full" id="risers-section">
          <div class="section-head">
            <h2>Fastest growing</h2>
            <div class="seg" id="riser-window" role="group" aria-label="Window">
              <button class="active" data-window="7">7d</button>
              <button data-window="30">30d</button>
              <button data-window="90">90d</button>
            </div>
          </div>
          <div class="riser-grid" id="riser-grid">
            <div class="empty">Loading…</div>
          </div>
        </section>
      </section>
    </main>
    <div id="toasts"></div>
    <script src="/vendor/echarts.min.js"></script>
    <script src="/charts.js"></script>
    <script src="/app.js"></script>
  </body>
</html>
````

### `web/styles.css`

Replace this file with the complete post-commit content below.

````css
/* GitHub Radar dashboard — base styles (v0.6) */
:root {
  --bg: #0d1117;
  --bg-elevated: #161b22;
  --bg-input: #0d1117;
  --border: #30363d;
  --text: #e6edf3;
  --text-muted: #8b949e;
  --accent: #58a6ff;
  --accent-strong: #1f6feb;
  --green: #3fb950;
  --yellow: #d29922;
  --red: #f85149;
  --radius: 8px;
  --shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, sans-serif;
  line-height: 1.5;
}
/* Top bar */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 24px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand h1 {
  font-size: 1.15rem;
  margin: 0;
  letter-spacing: 0.2px;
}
.logo {
  color: var(--accent);
}
.status-badge {
  font-size: 0.8rem;
  color: var(--text-muted);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 12px;
}
.status-badge.ok {
  color: var(--green);
  border-color: var(--green);
}
[hidden] {
  display: none !important;
}
.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.alert-bell {
  position: relative;
}
.alert-count {
  position: absolute;
  top: -6px;
  right: -7px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border: 2px solid var(--bg-elevated);
  border-radius: 999px;
  background: var(--red);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 14px;
  text-align: center;
}
.icon-btn,
.btn {
  background: var(--bg-input);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 8px 14px;
  font-size: 0.9rem;
  cursor: pointer;
}
.icon-btn {
  padding: 6px 10px;
}
.icon-btn:hover,
.btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.btn.small {
  padding: 5px 9px;
  font-size: 0.78rem;
}
/* Content */
.content {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
.placeholder {
  text-align: center;
  padding: 80px 20px;
  color: var(--text-muted);
}
.placeholder h2 {
  color: var(--text);
  margin-bottom: 8px;
}
/* Cards */
.card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 16px;
}
.card h2,
.card h3 {
  margin-top: 0;
}
/* Filters row */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 20px;
}
.filters input,
.filters select {
  background: var(--bg-input);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.9rem;
}
.filters input:focus,
.filters select:focus {
  outline: none;
  border-color: var(--accent);
}
/* Alert inbox */
.alerts-panel {
  margin-bottom: 20px;
  scroll-margin-top: 76px;
}
.alerts-head,
.alerts-actions,
.alerts-filters,
.alert-event-meta,
.alert-event-footer {
  display: flex;
  align-items: center;
}
.alerts-head {
  justify-content: space-between;
  gap: 16px;
}
.alerts-head h2 {
  margin-bottom: 2px;
}
.alerts-head p {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.82rem;
}
.alerts-actions,
.alerts-filters {
  gap: 8px;
}
.alerts-filters {
  margin: 16px 0 10px;
  flex-wrap: wrap;
}
.alerts-filters select {
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-input);
  color: var(--text);
}
.alert-events {
  display: grid;
  gap: 8px;
}
.alert-event {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg);
}
.alert-event.unread {
  border-left: 3px solid var(--accent);
}
.alert-event.read {
  opacity: 0.72;
}
.alert-event-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: rgba(88, 166, 255, 0.14);
}
.alert-event-body {
  min-width: 0;
}
.alert-event-meta,
.alert-event-footer {
  justify-content: space-between;
  gap: 10px;
}
.alert-event-meta {
  margin-bottom: 3px;
  color: var(--text-muted);
  font-size: 0.72rem;
}
.alert-event p {
  margin: 3px 0 8px;
  color: var(--text-muted);
  font-size: 0.84rem;
}
.alert-kind,
.delivery {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(88, 166, 255, 0.14);
  color: var(--accent);
  font-size: 0.7rem;
  text-transform: capitalize;
}
.delivery.failed {
  background: rgba(248, 81, 73, 0.14);
  color: var(--red);
}
.delivery.sent {
  background: rgba(63, 185, 80, 0.14);
  color: var(--green);
}
.link-btn {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
}
.link-btn:hover {
  text-decoration: underline;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
/* Layout grid */
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.grid .full {
  grid-column: 1 / -1;
}
/* Table */
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
th,
td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
th {
  color: var(--text-muted);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
th.sortable:hover {
  color: var(--accent);
}
th .arrow {
  font-size: 0.75rem;
}
tr.repo-row {
  cursor: pointer;
}
tr.repo-row:hover {
  background: rgba(88, 166, 255, 0.08);
}
tr.repo-row.selected {
  background: rgba(88, 166, 255, 0.15);
}
td.num,
th.num {
  text-align: right;
}
.lang-badge {
  display: inline-block;
  background: rgba(88, 166, 255, 0.15);
  color: var(--accent);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.78rem;
}
/* Chart area */
.chart-panel {
  min-height: 360px;
  display: flex;
  flex-direction: column;
}
.chart-panel .chart-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.chart-panel .chart-sub {
  color: var(--text-muted);
  font-size: 0.85rem;
  margin-bottom: 12px;
}
.cmp-col {
  width: 34px;
  text-align: center;
}
.cmp-col input {
  accent-color: var(--accent);
  cursor: pointer;
}
.compare-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin: 0 0 12px;
}
.chip {
  display: inline-block;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 0.75rem;
}
.burst-badge {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid var(--red);
  border-radius: 999px;
  background: rgba(248, 81, 73, 0.15);
  color: var(--red);
  font-size: 0.72rem;
  font-weight: 600;
  vertical-align: middle;
}
.chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.chart-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.seg {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.seg button {
  padding: 5px 10px;
  border: none;
  border-right: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-muted);
  font-size: 0.8rem;
  cursor: pointer;
}
.seg button:last-child {
  border-right: none;
}
.seg button.active {
  background: var(--accent-strong);
  color: #fff;
}
.seg button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted);
  font-size: 0.78rem;
  cursor: pointer;
  white-space: nowrap;
}
.toggle input {
  accent-color: var(--accent);
}
.toggle.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
#chart {
  flex: 1;
  min-height: 300px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.section-head h2 {
  margin: 0;
}
.riser-card .sub {
  color: var(--text-muted);
  font-size: 0.75rem;
}
/* New-this-week cards */
.riser-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.riser-card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
}
.riser-card .name {
  font-weight: 600;
  margin-bottom: 4px;
}
.riser-card .delta {
  color: var(--green);
  font-weight: 600;
}
.riser-card .rank {
  color: var(--text-muted);
  font-size: 0.78rem;
  margin-bottom: 2px;
}
.riser-card .bar {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  margin-top: 8px;
  overflow: hidden;
}
.riser-card .bar-fill {
  height: 100%;
  background: var(--green);
  border-radius: 2px;
}
/* Toasts */
#toasts {
  position: fixed;
  bottom: 16px;
  right: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 100;
}
.toast {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 0.85rem;
  max-width: 340px;
  box-shadow: var(--shadow);
  animation: toast-in 0.2s ease-out;
}
.toast.error {
  border-left-color: var(--red);
}
.toast.warn {
  border-left-color: var(--yellow);
}
@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
/* Empty state */
.empty {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 20px;
}
.empty .hint {
  font-size: 0.85rem;
  margin-top: 8px;
}
/* Spinner */
.spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: middle;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.spinner-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 0;
  color: var(--text-muted);
}
/* Light theme */
body.light {
  --bg: #ffffff;
  --bg-elevated: #f6f8fa;
  --bg-input: #ffffff;
  --border: #d0d7de;
  --text: #1f2328;
  --text-muted: #656d76;
  --shadow: 0 2px 8px rgba(140, 149, 159, 0.2);
}
/* Hover effects only on devices with a pointer */
@media (hover: hover) {
  tr.repo-row:hover {
    background: rgba(88, 166, 255, 0.08);
  }
  .riser-card:hover {
    border-color: var(--accent);
  }
}
/* Mobile */
@media (max-width: 860px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .alerts-head {
    align-items: flex-start;
  }
  .alert-event {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .alert-ack {
    grid-column: 2;
    justify-self: start;
  }
  .topbar {
    padding: 10px 16px;
  }
  .content {
    padding: 16px;
  }
  .filters {
    position: sticky;
    top: 58px;
    z-index: 5;
  }
  .filters input,
  .filters select {
    flex: 1 1 40%;
  }
  table {
    font-size: 0.8rem;
  }
  th,
  td {
    padding: 8px 10px;
  }
  #chart {
    min-height: 240px;
  }
}
/* --- analytics: leaderboard, velocity badges, burst strip --- */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.badge-velocity {
  background: rgba(46, 160, 67, 0.15);
  color: #3fb950;
}
.badge-trend {
  background: rgba(88, 166, 255, 0.15);
  color: #58a6ff;
}
.badge-burst {
  background: rgba(255, 123, 114, 0.15);
  color: #ff7b72;
}
.badges-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}
.mini-velocity {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(46, 160, 67, 0.15);
  color: #3fb950;
  white-space: nowrap;
}
.burst-strip-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  min-height: 14px;
}
.strip-label {
  font-size: 11px;
  color: rgba(139, 148, 158, 0.9);
  white-space: nowrap;
}
.strip-track {
  position: relative;
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: rgba(139, 148, 158, 0.12);
}
.burst-segment {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 4px;
  background: rgba(255, 123, 114, 0.55);
}
body.light .badge-velocity {
  color: #1a7f37;
}
body.light .badge-trend {
  color: #0969da;
}
body.light .badge-burst {
  color: #cf222e;
}
body.light .mini-velocity {
  color: #1a7f37;
}
body.light .burst-segment {
  background: rgba(207, 34, 46, 0.45);
}
````

## Verify

```bash
node --check web/app.js
pytest -q tests/test_api_contract.py
```

## Commit

```bash
git add -- \
  web/app.js \
  web/index.html \
  web/styles.css
git commit -m 'feat: add the alert inbox to the dashboard'
```
