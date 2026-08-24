const API = "/api/v1";

const state = {
  language: "",
  search: "",
  sort: "stars",
  period: "30",
  selectedRepo: null,
  selectedHistory: [],
  theme: localStorage.getItem("radar-theme") || "dark",
};

const el = (id) => document.getElementById(id);

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
        <th class="sortable num" data-sort="updated">Updated ${arrow("updated")}</th>
      </tr>
    </thead>
    <tbody>
      ${payload.items
        .map(
          (repo) => `
        <tr class="repo-row" data-full-name="${escapeHtml(repo.full_name)}">
          <td>${escapeHtml(repo.full_name)}</td>
          <td>${repo.language ? `<span class="lang-badge">${escapeHtml(repo.language)}</span>` : "—"}</td>
          <td class="num">${formatNumber(repo.stargazers_count)}</td>
          <td class="num">${formatNumber(repo.forks_count)}</td>
        </tr>`,
        )
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
  el("chart-sub").textContent = `${fullName} — star history`;
  try {
    const [detail, history] = await Promise.all([
      fetchJSON(`${API}/repos/${fullName}`),
      fetchJSON(`${API}/repos/${fullName}/history`),
    ]);
    state.selectedHistory = history;
    renderStarChart(fullName, filterByPeriod(history));
    const latest = detail.latest_snapshot;
    el("chart-sub").textContent = latest
      ? `${fullName} — ${formatNumber(latest.stargazers_count)} stars, ${formatNumber(latest.forks_count)} forks`
      : `${fullName} — no data yet`;
  } catch (err) {
    el("chart-sub").textContent = `${fullName} — failed to load history`;
    toast(err.message, "error");
  }
}

/* ---------- period switcher ---------- */

function filterByPeriod(history) {
  if (!history.length || state.period === "all") return history;
  const cutoff = Date.now() - Number(state.period) * 24 * 60 * 60 * 1000;
  return history.filter((s) => new Date(s.observed_at).getTime() >= cutoff);
}

function applyPeriod() {
  if (state.selectedRepo && state.selectedHistory.length) {
    renderStarChart(state.selectedRepo, filterByPeriod(state.selectedHistory));
  }
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
  if (state.selectedRepo && state.selectedHistory.length) {
    renderStarChart(state.selectedRepo, filterByPeriod(state.selectedHistory));
  }
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
  });

  refreshChartColors();
  refreshStatusBadge();
  loadLanguages();
  loadRepos();
  loadRisers();
}

document.addEventListener("DOMContentLoaded", init);
