/* GitHub Radar dashboard — application logic (built incrementally in v0.4). */

const API = "/api/v1";

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

async function refreshStatusBadge() {
  const badge = document.getElementById("status-badge");
  try {
    const health = await fetchJSON("/health");
    badge.textContent = health.status === "ok" ? "● online" : "● degraded";
    badge.classList.toggle("ok", health.status === "ok");
  } catch (_) {
    badge.textContent = "● offline";
  }
}

refreshStatusBadge();
