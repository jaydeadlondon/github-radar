const API = "/api/v1";
const state = {
  language: "",
  search: "",
  sort: "stars",
  period: "30",
  chartMode: "stars",
  selectedRepo: null,
  series: null,
  leaderboardWindow: "7",
  leaderboardCache: null,
  velocityMap: new Map(),
  theme: localStorage.getItem("radar-theme") || "dark",
};
const el = (id) => document.getElementById(id);
const periodDays = () => (state.period === "all" ? 365 : Number(state.period));
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
            ? `<span class="mini-velocity" title="${vel.stars_per_day} stars/day over ${state.leaderboardWindow}d">+${vel.stars_per_day}/d</span>`
            : "";
          return `
        <tr class="repo-row" data-full-name="${escapeHtml(repo.full_name)}">
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
      fetchJSON(`${API}/analytics/series/${fullName}?days=${periodDays()}`),
      loadVelocity(fullName),
      loadBursts(fullName),
    ]);
    state.series = series;
    renderChart();
    renderVelocityBadges(velocity);
    renderBurstStrip(bursts);
    const latest = detail.latest_snapshot;
    el("chart-sub").textContent = latest
      ? `${fullName} — ${formatNumber(latest.stargazers_count)} stars, ${formatNumber(latest.forks_count)} forks`
      : `${fullName} — no data yet`;
  } catch (err) {
    state.series = null;
    el("chart-sub").textContent = `${fullName} — failed to load history`;
    toast(err.message, "error");
  }
}
function renderChart() {
  if (!state.selectedRepo) {
    emptyChart("Select a repository to see its star history");
    return;
  }
  const points = state.series ? state.series.points : [];
  renderSeriesChart(state.selectedRepo, points, { mode: state.chartMode });
}
function setChartMode(mode) {
  state.chartMode = mode;
  document.querySelectorAll("#chart-mode button").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  renderChart();
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
async function loadBursts(fullName) {
  const [owner, name] = fullName.split("/");
  try {
    return await fetchJSON(
      `${API}/analytics/bursts/${encodeURIComponent(owner)}/${encodeURIComponent(name)}?days=90`,
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
    const start = end - 90 * 24 * 60 * 60 * 1000;
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
      `<span class="strip-label">Bursts · 90d</span><span class="strip-track">${segments}</span>`,
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
/* ---------- new this week (risers) ---------- */
async function loadRisers() {
  const grid = el("riser-grid");
  try {
    const risers = await fetchJSON(`${API}/trends?window=7&limit=8`);
    if (!risers.length) {
      grid.innerHTML =
        '<div class="empty">Not enough data yet — run <code>radar snapshot</code> for a few days.</div>';
      return;
    }
    const maxStars = Math.max(...risers.map((r) => r.stargazers_count));
    grid.innerHTML = risers
      .map((repo, index) => {
        const share = maxStars
          ? Math.round((repo.stargazers_count / maxStars) * 100)
          : 0;
        return `
        <div class="riser-card" data-full-name="${escapeHtml(repo.full_name)}">
          <div class="rank">#${index + 1}</div>
          <div class="name">${escapeHtml(repo.full_name)}</div>
          <div class="delta">★ ${formatNumber(repo.stargazers_count)} stars</div>
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
    grid.innerHTML = `<div class="empty">Failed to load risers.<div class="hint">${escapeHtml(err.message)}</div></div>`;
    toast(err.message, "error");
  }
}
/* ---------- fastest growing (leaderboard) ---------- */
function renderLeaderboard(payload) {
  const wrap = el("leaderboard-table-wrap");
  if (!payload.items.length) {
    wrap.innerHTML =
      '<div class="empty">Not enough history yet — run <code>radar snapshot</code> on several days.</div>';
    return;
  }
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th class="num">#</th>
        <th>Repository</th>
        <th>Language</th>
        <th class="num">Stars</th>
        <th class="num">Per day</th>
      </tr>
    </thead>
    <tbody>
      ${payload.items
        .map(
          (item) => `
        <tr class="lb-row" data-full-name="${escapeHtml(item.full_name)}">
          <td class="num">${item.rank}</td>
          <td>${escapeHtml(item.full_name)}</td>
          <td>${item.language ? `<span class="lang-badge">${escapeHtml(item.language)}</span>` : "—"}</td>
          <td class="num">${formatNumber(item.stars)}</td>
          <td class="num"><span class="badge badge-velocity">+${item.stars_per_day}/d</span></td>
        </tr>`,
        )
        .join("")}
    </tbody>
  `;
  wrap.innerHTML = "";
  wrap.appendChild(table);
  table.querySelectorAll("tr.lb-row").forEach((row) => {
    row.addEventListener("click", () => {
      state.search = "";
      el("search").value = "";
      selectRepo(row.dataset.fullName);
      loadRepos();
    });
  });
}
async function loadLeaderboard() {
  const wrap = el("leaderboard-table-wrap");
  wrap.innerHTML =
    '<div class="empty"><span class="spinner"></span> Loading leaderboard…</div>';
  try {
    const payload = await fetchJSON(
      `${API}/analytics/leaderboard?window=${state.leaderboardWindow}&limit=100`,
    );
    state.leaderboardCache = payload;
    state.velocityMap = new Map(
      payload.items.map((item) => [item.full_name, item]),
    );
    renderLeaderboard(payload);
    if (
      state.velocityMap.size &&
      el("repos-table-wrap").querySelector("table")
    ) {
      loadRepos();
    }
  } catch (err) {
    wrap.innerHTML = `<div class="empty">Failed to load leaderboard.<div class="hint">${escapeHtml(err.message)}</div></div>`;
    toast(err.message, "error");
  }
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
  el("language-filter").addEventListener("change", (event) => {
    state.language = event.target.value;
    loadRepos();
  });
  el("period-select").addEventListener("change", (event) => {
    state.period = event.target.value;
    applyPeriod();
  });
  el("chart-mode").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (!button || button.disabled) return;
    setChartMode(button.dataset.mode);
  });
  el("leaderboard-window").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-window]");
    if (!button) return;
    state.leaderboardWindow = button.dataset.window;
    el("leaderboard-window")
      .querySelectorAll("button")
      .forEach((b) => b.classList.toggle("active", b === button));
    loadLeaderboard();
  });
  let debounceTimer = null;
  el("theme-toggle").addEventListener("click", toggleTheme);
  el("search").addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(loadRepos, 300);
  });
  el("refresh-btn").addEventListener("click", () => {
    loadRepos();
    loadRisers();
    loadLeaderboard();
  });
  refreshChartColors();
  refreshStatusBadge();
  loadLanguages();
  loadLeaderboard();
  loadRepos();
  loadRisers();
}
document.addEventListener("DOMContentLoaded", init);
