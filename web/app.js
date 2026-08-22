const API = "/api/v1";

const state = {
  language: "",
  sort: "stars",
  selectedRepo: null,
  theme: localStorage.getItem("radar-theme") || "dark",
};

const el = (id) => document.getElementById(id);

/* ---------- helpers ---------- */

async function fetchJSON(path) {
  const response = await fetch(path);
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
    wrap.innerHTML =
      '<div class="empty">No repositories tracked yet.' +
      '<div class="hint">Run <code>radar top --save</code> on the server, then refresh.</div></div>';
    return;
  }

  const arrows = { stars: "↓", name: "", updated: "" };
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th class="sortable" data-sort="name">Repository</th>
        <th>Language</th>
        <th class="sortable num" data-sort="stars">Stars ${arrows.stars}</th>
        <th class="num">Forks</th>
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

async function loadRepos() {
  const params = new URLSearchParams({ sort: state.sort, limit: "100" });
  if (state.language) params.set("language", state.language);
  try {
    const payload = await fetchJSON(`${API}/repos?${params}`);
    renderReposTable(payload);
    if (
      state.selectedRepo &&
      payload.items.some((r) => r.full_name === state.selectedRepo)
    ) {
      selectRepo(state.selectedRepo);
    }
  } catch (err) {
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
    renderStarChart(fullName, history);
    const latest = detail.latest_snapshot;
    el("chart-sub").textContent = latest
      ? `${fullName} — ${formatNumber(latest.stargazers_count)} stars, ${formatNumber(latest.forks_count)} forks`
      : `${fullName} — no data yet`;
  } catch (err) {
    el("chart-sub").textContent = `${fullName} — failed to load history`;
    toast(err.message, "error");
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
            `<option value="${escapeHtml(lang.language)}">${escapeHtml(lang.language)}</option>`,
        )
        .join("");
  } catch (err) {
    toast(`Languages: ${err.message}`, "warn");
  }
}

/* ---------- init ---------- */

function init() {
  if (state.theme === "light") document.body.classList.add("light");
  el("theme-toggle").textContent = state.theme === "light" ? "☀️" : "🌙";

  el("language-filter").addEventListener("change", (event) => {
    state.language = event.target.value;
    loadRepos();
  });
  el("refresh-btn").addEventListener("click", () => {
    loadRepos();
  });

  refreshStatusBadge();
  loadLanguages();
  loadRepos();
}

document.addEventListener("DOMContentLoaded", init);
