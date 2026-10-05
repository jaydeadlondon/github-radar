const API = "/api/v1";
const state = {
  language: "",
  search: "",
  trackingStatus: "tracked",
  trackingLabel: "",
  sort: "stars",
  period: "30",
  chartMode: "stars",
  smooth: localStorage.getItem("radar-smooth") === "1",
  logScale: false,
  compare: new Set(),
  alertView: "unread",
  alertKind: "",
  alertSection: "inbox",
  alertsOpen: false,
  bursts: [],
  activeBurst: false,
  selectedRepo: null,
  series: null,
  tracking: null,
  riserWindow: "7",
  velocityMap: new Map(),
  theme: "dark",
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
    } catch (_) {}
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
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "—";
  }
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(
    value,
  );
}
function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZoneName: "short",
  });
}
function formatDay(value) {
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? "—" : date.toISOString().slice(0, 10);
}
function setRegionState(node, kind, message, options = {}) {
  if (!node) return;
  const hint = options.hint || "";
  node.innerHTML = "";
  const wrapper = document.createElement("div");
  wrapper.className = `empty ${kind}`;
  wrapper.setAttribute("role", kind === "error" ? "alert" : "status");
  const spinner =
    kind === "loading"
      ? '<span class="spinner" aria-hidden="true"></span> '
      : "";
  wrapper.innerHTML =
    spinner +
    escapeHtml(message) +
    (hint ? `<div class="hint">${escapeHtml(hint)}</div>` : "");
  if (typeof options.retry === "function") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn small";
    button.textContent = "Retry";
    button.addEventListener("click", options.retry);
    wrapper.appendChild(button);
  }
  node.appendChild(wrapper);
  setBusy(node, kind === "loading");
}
function setBusy(node, busy) {
  if (node) node.setAttribute("aria-busy", busy ? "true" : "false");
}
function announce(message) {
  const region = el("live-region");
  if (!region) return;
  region.textContent = "";
  window.setTimeout(() => {
    region.textContent = message;
  }, 50);
}
function describeError(err) {
  return err && err.message ? err.message : "unexpected error";
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
  } catch (err) {
    badge.textContent = "● offline";
    badge.title = `Health check failed: ${describeError(err)}`;
  }
}
/* ---------- alert inbox ---------- */
const ALERT_POLL_MS = 30000;
let alertEventsAbortController = null;
let alertPollTimer = null;
function alertKindLabel(kind) {
  return (
    {
      burst_started: "Burst",
      velocity_above: "Velocity",
      stars_reached: "Milestone",
    }[kind] || kind
  );
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
    if (state.alertsOpen) toast(`Alerts: ${describeError(err)}`, "warn");
  }
}
function renderAlertEvents(payload) {
  const container = el("alert-events");
  if (!payload.items.length) {
    container.innerHTML = `<div class="empty">${state.alertView === "unread" ? "No unread alerts." : "No alert events yet."}</div>`;
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
  const target = el("alert-events");
  setRegionState(target, "loading", "Loading alerts…");
  try {
    const payload = await fetchJSON(
      `${API}/alerts/events?${params}`,
      alertEventsAbortController.signal,
    );
    renderAlertEvents(payload);
    setBusy(target, false);
  } catch (err) {
    if (err.name === "AbortError") return;
    setRegionState(target, "error", "Failed to load alerts.", {
      hint: describeError(err),
      retry: loadAlertEvents,
    });
  }
}
let focusBeforeAlerts = null;
function setAlertsOpen(open) {
  const panel = el("alerts-panel");
  state.alertsOpen = open;
  panel.hidden = !open;
  el("alerts-toggle").setAttribute("aria-expanded", String(open));
  if (open) {
    focusBeforeAlerts = document.activeElement;
    loadAlertSummary();
    setAlertSection(state.alertSection);
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    if (alertEventsAbortController) alertEventsAbortController.abort();
    const restore = focusBeforeAlerts || el("alerts-toggle");
    if (restore && typeof restore.focus === "function") restore.focus();
    focusBeforeAlerts = null;
  }
}
/* Arrow-key navigation for segmented controls, with a roving tabindex so the
   whole group is one tab stop. */
function initSegGroup(group) {
  const buttons = [...group.querySelectorAll("button")];
  if (!buttons.length) return;
  buttons.forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.classList.contains("active")),
    );
    button.tabIndex = button.classList.contains("active") ? 0 : -1;
  });
  group.addEventListener("keydown", (event) => {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const items = [...group.querySelectorAll("button")].filter(
      (button) => !button.disabled,
    );
    const current = items.indexOf(document.activeElement);
    if (current === -1) return;
    event.preventDefault();
    let next = current;
    if (event.key === "ArrowLeft")
      next = (current - 1 + items.length) % items.length;
    if (event.key === "ArrowRight") next = (current + 1) % items.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = items.length - 1;
    items.forEach((item, index) => {
      item.tabIndex = index === next ? 0 : -1;
    });
    items[next].focus();
    items[next].click();
  });
}
function syncSegGroup(group) {
  group.querySelectorAll("button").forEach((button) => {
    const active = button.classList.contains("active");
    button.setAttribute("aria-pressed", String(active));
    button.tabIndex = active ? 0 : -1;
  });
}
async function acknowledgeAlert(eventId) {
  try {
    await sendJSON(`${API}/alerts/events/${eventId}`, "PATCH", {
      acknowledged: true,
    });
    await Promise.all([loadAlertSummary(), loadAlertEvents()]);
  } catch (err) {
    toast(describeError(err), "error");
  }
}
async function acknowledgeAllAlerts() {
  try {
    const result = await sendJSON(
      `${API}/alerts/events/acknowledge-all`,
      "POST",
    );
    toast(`Marked ${result.acknowledged} alert(s) as read`);
    await Promise.all([loadAlertSummary(), loadAlertEvents()]);
  } catch (err) {
    toast(describeError(err), "error");
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
let alertRulesAbortController = null;
function ruleCondition(rule) {
  if (rule.kind === "velocity_above") {
    return `${rule.threshold} stars/day over ${rule.window_days} days`;
  }
  if (rule.kind === "stars_reached") {
    return `${formatNumber(rule.threshold)} stars`;
  }
  return "When a new burst starts";
}
function renderAlertRules(payload) {
  const container = el("alert-rules");
  if (!payload.items.length) {
    container.innerHTML =
      '<div class="empty">No alert rules yet.<div class="hint">Create one above to start watching a repository.</div></div>';
    return;
  }
  container.innerHTML = payload.items
    .map(
      (rule) => `
        <article class="alert-rule ${rule.enabled ? "enabled" : "disabled"}">
          <div>
            <div class="alert-rule-title">
              <strong>${escapeHtml(rule.repository)}</strong>
              <span class="alert-kind">${escapeHtml(alertKindLabel(rule.kind))}</span>
            </div>
            <p>${escapeHtml(ruleCondition(rule))}</p>
          </div>
          <div class="alert-rule-actions">
            <button class="btn small" data-rule-action="toggle" data-rule-id="${rule.id}"
              data-rule-enabled="${rule.enabled}">
              ${rule.enabled ? "Disable" : "Enable"}
            </button>
            <button class="btn small danger" data-rule-action="delete" data-rule-id="${rule.id}">
              Delete
            </button>
          </div>
        </article>`,
    )
    .join("");
}
async function loadAlertRules() {
  if (!state.alertsOpen || state.alertSection !== "rules") return;
  if (alertRulesAbortController) alertRulesAbortController.abort();
  alertRulesAbortController = new AbortController();
  const target = el("alert-rules");
  setRegionState(target, "loading", "Loading rules…");
  try {
    const payload = await fetchJSON(
      `${API}/alerts/rules?limit=100`,
      alertRulesAbortController.signal,
    );
    renderAlertRules(payload);
    setBusy(target, false);
  } catch (err) {
    if (err.name === "AbortError") return;
    setRegionState(target, "error", "Failed to load rules.", {
      hint: describeError(err),
      retry: loadAlertRules,
    });
  }
}
async function loadAlertRuleRepositories() {
  const select = el("alert-rule-repository");
  try {
    const payload = await fetchJSON(`${API}/repos?sort=name&limit=100`);
    select.innerHTML =
      '<option value="">Select a tracked repository</option>' +
      payload.items
        .map(
          (repo) =>
            `<option value="${escapeHtml(repo.full_name)}">${escapeHtml(repo.full_name)}</option>`,
        )
        .join("");
    el("alert-rule-submit").disabled = payload.items.length === 0;
  } catch (err) {
    select.innerHTML = '<option value="">Repositories unavailable</option>';
    el("alert-rule-submit").disabled = true;
    toast(`Alert rules: ${describeError(err)}`, "warn");
  }
}
function syncAlertRuleFields() {
  const kind = el("alert-rule-kind").value;
  const needsThreshold = kind !== "burst_started";
  const needsWindow = kind === "velocity_above";
  el("alert-threshold-field").hidden = !needsThreshold;
  el("alert-window-field").hidden = !needsWindow;
  el("alert-rule-threshold").required = needsThreshold;
  el("alert-rule-window").required = needsWindow;
  el("alert-rule-threshold").step = kind === "stars_reached" ? "1" : "0.01";
}
async function createAlertRule(event) {
  event.preventDefault();
  const kind = el("alert-rule-kind").value;
  const threshold = el("alert-rule-threshold").value;
  const payload = {
    repository: el("alert-rule-repository").value,
    kind,
    threshold: kind === "burst_started" ? null : Number(threshold),
    window_days:
      kind === "velocity_above" ? Number(el("alert-rule-window").value) : null,
  };
  try {
    await sendJSON(`${API}/alerts/rules`, "POST", payload);
    toast("Alert rule created");
    el("alert-rule-form").reset();
    syncAlertRuleFields();
    await Promise.all([loadAlertRules(), loadAlertSummary()]);
  } catch (err) {
    toast(describeError(err), "error");
  }
}
async function changeAlertRule(ruleId, action, currentlyEnabled) {
  try {
    if (action === "delete") {
      if (
        !window.confirm("Delete this alert rule? Existing events will be kept.")
      )
        return;
      await sendJSON(`${API}/alerts/rules/${ruleId}`, "DELETE");
      toast("Alert rule deleted");
    } else {
      await sendJSON(`${API}/alerts/rules/${ruleId}`, "PATCH", {
        enabled: !currentlyEnabled,
      });
      toast(`Alert rule ${currentlyEnabled ? "disabled" : "enabled"}`);
    }
    await Promise.all([loadAlertRules(), loadAlertSummary()]);
  } catch (err) {
    toast(describeError(err), "error");
  }
}
function setAlertSection(section) {
  state.alertSection = section;
  el("alert-inbox-pane").hidden = section !== "inbox";
  el("alert-rules-pane").hidden = section !== "rules";
  el("acknowledge-all").hidden = section !== "inbox";
  el("alert-section")
    .querySelectorAll("button")
    .forEach((button) => {
      button.classList.toggle("active", button.dataset.section === section);
    });
  syncSegGroup(el("alert-section"));
  if (section === "rules") {
    loadAlertRuleRepositories();
    loadAlertRules();
  } else {
    loadAlertEvents();
  }
}
/* ---------- repositories table ---------- */
function renderReposTable(payload) {
  const wrap = el("repos-table-wrap");
  if (!payload.items.length) {
    const filtered =
      state.language ||
      state.search ||
      state.trackingLabel ||
      state.trackingStatus !== "tracked";
    if (filtered) {
      wrap.innerHTML =
        '<div class="empty" role="status">Nothing matches your filters.' +
        '<div class="hint">Try a different language or search term, ' +
        "or clear the filters to see every repository.</div></div>";
      setBusy(wrap, false);
    } else {
      el("risers-section").style.display = "none";
      wrap.innerHTML =
        '<div class="empty" role="status">No repositories tracked yet.' +
        '<div class="hint">Run <code>radar top --save</code> on the server, ' +
        "or track one with the form above, then refresh.</div></div>";
      setBusy(wrap, false);
      emptyChart("Select a repository to see its star history");
    }
    return;
  }
  el("risers-section").style.display = "";
  setBusy(wrap, false);
  const arrow = (key) =>
    state.sort === key
      ? '<span class="arrow">↓</span>'
      : '<span class="arrow">↕</span>';
  const ariaSort = (key) =>
    state.sort === key ? (key === "name" ? "ascending" : "descending") : "none";
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th class="cmp-col" title="Pick two or more to compare"><span class="sr-only">Compare</span>⇄</th>
        <th class="sortable" data-sort="name" aria-sort="${ariaSort("name")}">
          <button type="button" class="th-sort">Repository ${arrow("name")}<span class="sr-only">, sort by name</span></button>
        </th>
        <th>Language</th>
        <th>Status</th>
        <th>Label</th>
        <th class="sortable num" data-sort="stars" aria-sort="${ariaSort("stars")}">
          <button type="button" class="th-sort">Stars ${arrow("stars")}<span class="sr-only">, sort by stars</span></button>
        </th>
        <th class="num">Forks</th>
        <th>Actions</th>
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
        <tr class="repo-row" data-full-name="${escapeHtml(repo.full_name)}"
            tabindex="0" aria-label="Repository ${escapeHtml(repo.full_name)}">
          <td class="cmp-col">
            <input type="checkbox" class="cmp-box"
              data-full-name="${escapeHtml(repo.full_name)}"
              aria-label="Compare ${escapeHtml(repo.full_name)}"
              ${state.compare.has(repo.full_name) ? "checked" : ""} />
          </td>
          <td>${escapeHtml(repo.full_name)} ${velBadge}</td>
          <td>${repo.language ? `<span class="lang-badge">${escapeHtml(repo.language)}</span>` : "—"}</td>
          <td>
            <span
              class="tracking-badge ${escapeHtml(repo.tracking_status || "stale")}"
              title="${escapeHtml(repo.last_snapshot_error || "")}"
              aria-label="Tracking status: ${escapeHtml(repo.tracking_status || "stale")}${
                repo.last_snapshot_error
                  ? `. Last error: ${escapeHtml(repo.last_snapshot_error)}`
                  : ""
              }"
            >${escapeHtml(repo.tracking_status || "stale")}</span>
          </td>
          <td>${repo.tracking_label ? escapeHtml(repo.tracking_label) : "—"}</td>
          <td class="num">${formatNumber(repo.stargazers_count)}</td>
          <td class="num">${formatNumber(repo.forks_count)}</td>
          <td class="repo-actions">
            ${
              repo.tracking_paused
                ? `<button class="btn small repo-action" data-repo-action="resume" data-repo-name="${escapeHtml(repo.full_name)}">Resume</button>`
                : repo.tracking_enabled
                  ? `<button class="btn small repo-action" data-repo-action="pause" data-repo-name="${escapeHtml(repo.full_name)}">Pause</button>`
                  : `<button class="btn small repo-action" data-repo-action="track" data-repo-name="${escapeHtml(repo.full_name)}">Track</button>`
            }
            ${repo.tracking_enabled ? `<button class="btn small danger repo-action" data-repo-action="untrack" data-repo-name="${escapeHtml(repo.full_name)}">Stop</button>` : ""}
            <button class="btn small repo-action" data-repo-action="refresh" data-repo-name="${escapeHtml(repo.full_name)}">Refresh</button>
          </td>
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
    const button = th.querySelector("button.th-sort");
    if (button)
      button.addEventListener("click", (event) => event.stopPropagation());
  });
  table.querySelectorAll("tr.repo-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectRepo(row.dataset.fullName);
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectRepo(row.dataset.fullName);
      }
    });
  });
  table.querySelectorAll("input.cmp-box").forEach((box) => {
    box.addEventListener("click", (event) => event.stopPropagation());
    box.addEventListener("change", () => toggleCompare(box));
  });
  table.querySelectorAll("button.repo-action").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      changeRepositoryTracking(
        button.dataset.repoName,
        button.dataset.repoAction,
      );
    });
  });
}
async function changeRepositoryTracking(fullName, action) {
  const [owner, name] = fullName.split("/");
  if (
    action === "untrack" &&
    !window.confirm(
      `Stop tracking ${fullName}?\n\nIts history stays in the database and can be restored by tracking the repository again.`,
    )
  ) {
    return;
  }
  try {
    if (action === "refresh") {
      await sendJSON(
        `${API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/refresh`,
        "POST",
      );
      toast(`Refreshed ${fullName}`);
    } else if (action === "untrack") {
      await sendJSON(
        `${API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/track`,
        "DELETE",
      );
      toast(`Stopped tracking ${fullName}`);
    } else if (action === "track") {
      await sendJSON(
        `${API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/track`,
        "POST",
        {},
      );
      toast(`Tracking ${fullName}`);
    } else {
      await sendJSON(
        `${API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/tracking`,
        "PATCH",
        { paused: action === "pause" },
      );
      toast(`${action === "pause" ? "Paused" : "Resumed"} ${fullName}`);
    }
    announce(`${action} ${fullName} finished`);
    await loadRepos();
    if (state.selectedRepo === fullName) await selectRepo(fullName);
  } catch (err) {
    toast(describeError(err), "error");
  }
}
async function trackRepositoryFromForm(event) {
  event.preventDefault();
  const fullName = el("track-repository").value.trim();
  const label = el("track-label").value.trim();
  if (!fullName || fullName.split("/").length !== 2) {
    toast("Use owner/name format", "warn");
    return;
  }
  const [owner, name] = fullName.split("/");
  try {
    await sendJSON(
      `${API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/track`,
      "POST",
      label ? { label } : {},
    );
    el("track-repository").value = "";
    el("track-label").value = "";
    toast(`Tracking ${fullName}`);
    announce(`Now tracking ${fullName}`);
    await loadRepos();
  } catch (err) {
    toast(describeError(err), "error");
  }
}
function showTableSpinner() {
  setRegionState(el("repos-table-wrap"), "loading", "Loading repositories…");
}
let reposAbortController = null;
async function loadRepos() {
  if (reposAbortController) reposAbortController.abort();
  reposAbortController = new AbortController();
  const params = new URLSearchParams({ sort: state.sort, limit: "100" });
  if (state.language) params.set("language", state.language);
  if (state.search) params.set("q", state.search);
  if (
    ["tracked", "active", "paused", "untracked", "all"].includes(
      state.trackingStatus,
    )
  ) {
    params.set("tracking", state.trackingStatus);
  } else if (state.trackingStatus) {
    params.set("tracking_status", state.trackingStatus);
  }
  if (state.trackingLabel) params.set("label", state.trackingLabel);
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
    setRegionState(
      el("repos-table-wrap"),
      "error",
      "Failed to load repositories.",
      {
        hint: describeError(err),
        retry: loadRepos,
      },
    );
    toast(describeError(err), "error");
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
    state.tracking = detail.tracking || null;
    state.bursts = bursts ? bursts.items : [];
    state.activeBurst = bursts ? bursts.active_burst : false;
    renderChart();
    renderVelocityBadges(velocity);
    renderBurstStrip(bursts);
    renderChartSubtitle(fullName, detail.latest_snapshot);
  } catch (err) {
    state.series = null;
    state.tracking = null;
    state.bursts = [];
    state.activeBurst = false;
    el("chart-sub").textContent = `${fullName} — failed to load history`;
    toast(describeError(err), "error");
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
  if (state.tracking) {
    parts.push(`tracking: ${state.tracking.status}`);
    if (
      state.tracking.status === "failed" &&
      state.tracking.last_snapshot_error
    ) {
      parts.push(`last error: ${state.tracking.last_snapshot_error}`);
    }
    if (
      state.tracking.snapshot_count < 2 &&
      state.tracking.status !== "failed"
    ) {
      parts.push("not enough data for analytics");
    }
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
  bar.setAttribute(
    "aria-label",
    `${state.compare.size} repositories selected for comparison`,
  );
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
    el("chart-sub").textContent = `Comparison failed — ${describeError(err)}`;
    toast(describeError(err), "error");
  }
}
function renderChart() {
  if (state.compare.size >= 2) {
    renderComparison();
    return;
  }
  if (!state.selectedRepo) {
    emptyChart("Select a repository to see its star history");
    el("chart-notice").textContent = "";
    return;
  }
  const points = state.series ? state.series.points : [];
  renderChartIssues();
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
  syncSegGroup(el("chart-mode"));
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
  } catch (err) {
    noteChartIssue(`velocity unavailable (${describeError(err)})`);
    return null;
  }
}
async function loadBursts(fullName, days = 90) {
  const [owner, name] = fullName.split("/");
  try {
    return await fetchJSON(
      `${API}/analytics/bursts/${encodeURIComponent(owner)}/${encodeURIComponent(name)}?days=${days}`,
    );
  } catch (err) {
    noteChartIssue(`burst detection unavailable (${describeError(err)})`);
    return null;
  }
}
let chartIssues = [];
function noteChartIssue(message) {
  if (!chartIssues.includes(message)) chartIssues.push(message);
}
function renderChartIssues() {
  const notice = el("chart-notice");
  if (!notice) return;
  notice.textContent = chartIssues.join(" · ");
  chartIssues = [];
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
    const select = el("language-filter");
    select.innerHTML = '<option value="">Languages unavailable</option>';
    toast(`Languages: ${describeError(err)}`, "warn");
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
      setBusy(grid, false);
      grid.innerHTML =
        '<div class="empty" role="status">Not enough data yet.' +
        '<div class="hint">Run <code>radar snapshot</code> for a few days to see risers.</div></div>';
      return;
    }
    const fastest = Math.max(...risers.map((repo) => repo.stars_per_day));
    grid.innerHTML = risers
      .map((repo) => {
        const share = fastest
          ? Math.round((repo.stars_per_day / fastest) * 100)
          : 0;
        return `
        <button type="button" class="riser-card" data-full-name="${escapeHtml(repo.full_name)}"
          aria-label="Rank ${repo.rank}: ${escapeHtml(repo.full_name)}, plus ${repo.stars_per_day} stars per day">
          <span class="rank">#${repo.rank}</span>
          <span class="name">${escapeHtml(repo.full_name)}</span>
          <span class="delta">+${formatNumber(repo.stars_per_day)} stars/day</span>
          <span class="sub">+${formatNumber(repo.stars_gained)} in ${state.riserWindow}d · ★ ${formatNumber(repo.stars)}</span>
          <span class="bar"><span class="bar-fill" style="width:${share}%"></span></span>
        </button>`;
      })
      .join("");
    setBusy(grid, false);
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
    setRegionState(grid, "error", "Failed to load risers.", {
      hint: describeError(err),
      retry: loadLeaderboardAndRepos,
    });
    toast(describeError(err), "error");
  }
}
function loadLeaderboardAndRepos() {
  return loadRisers().finally(loadRepos);
}
async function refreshAll() {
  const button = el("refresh-btn");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  announce("Refreshing dashboard");
  try {
    await Promise.all([
      loadLeaderboardAndRepos(),
      loadLanguages(),
      loadAlertSummary(),
      refreshStatusBadge(),
    ]);
    if (state.alertsOpen) await loadAlertEvents();
    announce("Dashboard refreshed");
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}
/* ---------- theme ---------- */
function storedTheme() {
  const saved = localStorage.getItem("radar-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}
function applyTheme() {
  state.theme = storedTheme();
  document.body.classList.toggle("light", state.theme === "light");
  const button = el("theme-toggle");
  button.textContent = state.theme === "light" ? "☀️" : "🌙";
  button.setAttribute(
    "aria-label",
    state.theme === "light" ? "Switch to dark theme" : "Switch to light theme",
  );
}
function toggleTheme() {
  localStorage.setItem(
    "radar-theme",
    document.body.classList.contains("light") ? "dark" : "light",
  );
  applyTheme();
  refreshChartColors();
  renderChart();
}
/* ---------- init ---------- */
function init() {
  applyTheme();
  renderCompareBar();
  syncToolbar();
  syncAlertRuleFields();
  el("alerts-toggle").addEventListener("click", () => {
    setAlertsOpen(!state.alertsOpen);
  });
  el("alerts-close").addEventListener("click", () => setAlertsOpen(false));
  el("acknowledge-all").addEventListener("click", acknowledgeAllAlerts);
  el("alert-section").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-section]");
    if (button) setAlertSection(button.dataset.section);
  });
  el("alert-rule-kind").addEventListener("change", syncAlertRuleFields);
  el("alert-rule-form").addEventListener("submit", createAlertRule);
  el("alert-rules").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-rule-action]");
    if (!button) return;
    changeAlertRule(
      button.dataset.ruleId,
      button.dataset.ruleAction,
      button.dataset.ruleEnabled === "true",
    );
  });
  el("alert-view").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    state.alertView = button.dataset.view;
    el("alert-view")
      .querySelectorAll("button")
      .forEach((item) => item.classList.toggle("active", item === button));
    syncSegGroup(el("alert-view"));
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
  el("tracking-status-filter").addEventListener("change", (event) => {
    state.trackingStatus = event.target.value;
    loadRepos();
  });
  let labelFilterTimer = null;
  el("tracking-label-filter").addEventListener("input", (event) => {
    state.trackingLabel = event.target.value.trim();
    clearTimeout(labelFilterTimer);
    labelFilterTimer = setTimeout(loadRepos, 250);
  });
  el("track-btn").addEventListener("click", trackRepositoryFromForm);
  el("track-repository").addEventListener("keydown", (event) => {
    if (event.key === "Enter") trackRepositoryFromForm(event);
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
    syncSegGroup(el("riser-window"));
    loadLeaderboardAndRepos();
  });
  ["alert-section", "alert-view", "chart-mode", "riser-window"].forEach(
    (id) => {
      const group = el(id);
      if (group) initSegGroup(group);
    },
  );
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.alertsOpen) setAlertsOpen(false);
  });
  let debounceTimer = null;
  el("theme-toggle").addEventListener("click", toggleTheme);
  el("search").addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(loadRepos, 300);
  });
  el("refresh-btn").addEventListener("click", refreshAll);
  refreshChartColors();
  refreshStatusBadge();
  loadLanguages();
  loadLeaderboardAndRepos();
  startAlertPolling();
}
document.addEventListener("DOMContentLoaded", init);
