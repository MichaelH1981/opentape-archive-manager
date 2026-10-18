import {
  $,
  $$,
  esc,
  short,
  newId,
  bytes,
  num,
  date,
  ago,
  labels,
  badge,
  kindLabel,
  titles,
} from "./common.js";
import { icon } from "./icons.js";
import { state } from "./state.js";
import { toast } from "./ui.js";
async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (options.body) {
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = state.csrf;
  }
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (e) {
    throw new Error("Der Node ist nicht erreichbar. Verbindung prüfen.");
  }
  let result;
  try {
    result = await response.json();
  } catch (e) {
    throw new Error(
      `Serverantwort konnte nicht gelesen werden (HTTP ${response.status})`,
    );
  }
  if (!response.ok) {
    if (response.status === 401 && path != "/login")
      document.dispatchEvent(new Event("otam:unauthorized"));
    const detail = result.error || result.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : "Eingaben konnten nicht verarbeitet werden.",
    );
  }
  return result;
}
async function enqueue(kind, payload) {
  const result = await api("/commands", {
    method: "POST",
    headers: { "Idempotency-Key": newId() },
    body: JSON.stringify({ kind, payload }),
  });
  toast(`${kindLabel(kind)} wurde in die Warteschlange aufgenommen.`);
  await refreshBase();
  return result;
}
async function refreshBase() {
  const [n, o, m] = await Promise.all([
    api("/node"),
    api("/overview"),
    api("/media"),
  ]);
  state.node = n;
  state.overview = o;
  state.media = m.items;
  if (n.role === "archive") state.commands = (await api("/commands")).items;
  $("#node-name").textContent = n.name;
  const role = n.role === "archive" ? "Archive Node" : "Catalog Node";
  $("#node-role").textContent = role;
  $("#role-pill").innerHTML = `<span class="status-dot"></span>${role}`;
  $("#footer-mode").textContent =
    n.role === "archive"
      ? n.operation_mode === "physical"
        ? "Physische Bandwartung"
        : "Simulatorbetrieb"
      : role;
  $$("[data-archive]").forEach((e) => (e.hidden = n.role !== "archive"));
  const running = state.commands.filter((c) =>
    ["QUEUED", "RUNNING"].includes(c.state),
  ).length;
  $("#nav-jobs").hidden = !running;
  $("#nav-jobs").textContent = running;
  $("#last-refresh").textContent =
    "Aktualisiert " +
    new Date().toLocaleTimeString("de-DE", {
      hour: "2-digit",
      minute: "2-digit",
    });
  $("#connection-label").textContent = "Mit Node verbunden";
  $("#connection-dot").classList.remove("off");
  for (const c of state.commands) {
    if (
      !state.notified.has(c.id) &&
      ["FAILED", "INTERRUPTED"].includes(c.state)
    ) {
      state.notified.add(c.id);
      if (Date.now() / 1000 - c.updated < 20)
        toast(`${kindLabel(c.kind)}: ${c.error || labels[c.state]}`, true);
    }
  }
}

export { api, enqueue, refreshBase };
