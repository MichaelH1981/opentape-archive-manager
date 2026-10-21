import {
  $,
  $$,
  esc,
  short,
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
import { localize, translate } from "./i18n.js";
function paintIcons(root = document) {
  $$("[data-icon]", root).forEach((e) => (e.innerHTML = icon(e.dataset.icon)));
}
function toast(text, error = false) {
  const e = document.createElement("div");
  e.className = "toast" + (error ? " error" : "");
  e.textContent = translate(text);
  $("#toasts").append(e);
  setTimeout(() => e.remove(), error ? 10000 : 6500);
}
function heading(title, description, actions = "") {
  return `<div class="page-heading"><div><span class="eyebrow">DEIN LANGZEITARCHIV</span><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${actions ? `<div class="page-actions">${actions}</div>` : ""}</div>`;
}
const linkButton = (text, href, ic = "arrow", primary = false) =>
  `<a class="button ${primary ? "primary" : ""}" href="#${href}">${icon(ic)}${esc(text)}</a>`;
const empty = (title, text, ic = "archive", action = "", compact = false) =>
  `<div class="empty ${compact ? "compact" : ""}"><div class="empty-icon">${icon(ic)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
const note = (text, type = "") =>
  `<div class="note ${type}">${icon(type === "warning" ? "info" : "shield")}<span>${esc(text)}</span></div>`;
const progress = (p) => {
  const known = p !== null && p !== undefined && Number.isFinite(Number(p));
  const value = Math.max(0, Math.min(100, Number(p) || 0));
  return `<div class="progress${known ? "" : " is-indeterminate"}" role="progressbar" aria-label="${known ? "Fortschritt" : "Gesamtmenge noch unbekannt"}" ${known ? `aria-valuemin="0" aria-valuemax="100" aria-valuenow="${value.toFixed(1)}"` : ""}><span style="width:${known ? value : 35}%"></span></div><div class="subtle-caption">${known ? value.toFixed(1) + " %" : "Laufende Aktivität · Gesamtfortschritt unbekannt"}</div>`;
};
function jobProgress(p) {
  if (!p) return "";
  if (["WAITING_MEDIA","PLANNED","STAGED"].includes(p.job_state))
    return `<div class="job-progress"><p><strong>Plan bereit · wartet auf Bestätigung</strong></p><p>Medium ${num(p.medium_index)} / ${num(p.medium_count)} · ${num(p.archives_verified)} / ${num(p.archives_total)} TARs dieses Mediums verifiziert</p></div>`;
  return `<div class="job-progress"><div class="progress-meta"><strong>${esc(labels[p.phase] || p.phase)}</strong><span>Medium ${num(p.medium_index)} / ${num(p.medium_count)} · ${num(p.archives_verified)} / ${num(p.archives_total)} TARs verifiziert</span></div>${progress(p.percent)}<p class="hint">${p.percent === null ? "" : `${bytes(p.bytes)} / ${bytes(p.total_bytes)} · `}Letzter Stand ${esc(ago(p.updated))}${p.phase === "TAPE_READBACK" && p.percent === 100 && p.job_state !== "VERIFIED" ? " · Lesepass beendet; Abschlussprüfungen laufen noch." : ""}</p></div>`;
}
function modal(title, html) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  paintIcons($("#modal"));
  localize($("#modal"));
  if (!$("#modal").open) $("#modal").showModal();
}
function closeModal() {
  $("#modal").close();
}
function sourceName(id) {
  return state.node.sources.find((s) => s.id === id)?.label || id;
}
function mediaName(id) {
  return state.media.find((m) => m.id === id)?.label || short(id);
}
function mediaOptions() {
  return state.media
    .filter((m) => m.mounted)
    .map(
      (m) =>
        `<option value="${esc(m.id)}">${esc(m.label)} · ${esc(labels[m.state] || m.state)}</option>`,
    )
    .join("");
}
function table(columns, rows, emptyText = "Noch keine Einträge vorhanden") {
  return rows.length
    ? `<div class="table-wrap"><table><thead><tr>${columns.map((c) => `<th scope="col">${c}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : empty(
        emptyText,
        "Sobald Daten vorliegen, erscheinen sie hier.",
        "archive",
        "",
        true,
      );
}
function pipeline(phase) {
  const phases = [
    "INVENTORY",
    "STAGING",
    "VALIDATION",
    "READY",
    "TAPE_WRITE",
    "TAPE_READBACK",
    "VERIFIED",
    "STAGING_CLEANUP",
  ];
  const idx = phases.indexOf(phase);
  return `<div class="pipeline">${phases.map((p, i) => `<div class="pipeline-step ${i < idx ? "done" : i === idx ? "current" : ""}"><span class="pipeline-circle">${i < idx ? "✓" : i + 1}</span>${esc({ INVENTORY: "Inventar", STAGING: "Staging", VALIDATION: "Prüfen", READY: "Bereit", TAPE_WRITE: "Schreiben", TAPE_READBACK: "Rücklesen", VERIFIED: "Verifiziert", STAGING_CLEANUP: "Bereinigt" }[p])}</div>`).join("")}</div>`;
}
function storageCard(storage) {
  if (!storage)
    return `<section class="panel storage-card"><h2>Katalog-Replikat</h2><p>Eigenständig verfügbar, auch ohne laufenden Bandserver.</p><div class="node-detail">${icon("sync")}<div><strong>${state.node.snapshot ? ago(state.node.snapshot.created) : "Noch kein Katalog empfangen"}</strong><small>Stand des Primärkatalogs</small></div></div></section>`;
  const percent = storage.total ? Math.min(100, Math.round((storage.used / storage.total) * 100)) : 0,
    circ = 326.7;
  return `<section class="panel storage-card"><h2>Lokaler Staging-Speicher</h2><p>Vorbereiten. Prüfen. Sicher schreiben.</p><div class="storage-ring"><svg viewBox="0 0 127 127" aria-hidden="true"><circle class="track" cx="63.5" cy="63.5" r="52"/><circle class="fill" cx="63.5" cy="63.5" r="52" stroke-dasharray="${(circ * percent) / 100} ${circ}"/></svg><div class="ring-text"><strong>${percent}<small>%</small></strong><small>belegt</small></div></div><div class="legend-row"><span class="legend-dot"></span>Gesamtkapazität<strong>${bytes(storage.total)}</strong></div><div class="legend-row"><span class="legend-dot"></span>Belegt<strong>${bytes(storage.used)}</strong></div><div class="legend-row"><span class="legend-dot light"></span>Verfügbar<strong>${bytes(storage.free)}</strong></div></section>`;
}
function sparkline(samples) {
  const vals = samples
    .map((s) => Number(s.details?.bytes_per_second || 0))
    .reverse();
  if (vals.length < 2)
    return `<div class="sparkline subtle-caption">Messwerte erscheinen während eines laufenden Transfers.</div>`;
  const max = Math.max(...vals, 1),
    points = vals
      .map((v, i) => `${(i / (vals.length - 1)) * 300},${51 - (v / max) * 42}`)
      .join(" ");
  return `<svg class="sparkline" viewBox="0 0 300 56" preserveAspectRatio="none" aria-label="Gemessener Datendurchsatz"><path d="M0 52H300" fill="none" stroke="#edf1e6"/><polyline points="${points}" fill="none" stroke="#8ba96e" stroke-width="1.8"/></svg>`;
}
function eventLabel(e) {
  return (
    {
      job_finished: "Job " + (labels[e.details.state] || "abgeschlossen"),
      plan_ready: "Archivplan ist bereit",
      confirmed: "Archivierung bestätigt",
      job_created: kindLabel(e.details.kind) + " angelegt",
      io_progress: "Datentransfer",
      staging_progress: "Archiv wird lokal vorbereitet",
      job_phase: "Phase: " + (labels[e.details.phase] || e.details.phase),
      staging_read_sample: "Staging-Lesetest",
    }[e.event] || e.event
  );
}
function queuePanel() {
  if (state.node.role !== "archive") return "";
  const active = state.commands
    .filter((c) =>
      ["QUEUED", "RUNNING", "INTERRUPTED", "FAILED"].includes(c.state),
    )
    .slice(0, 8);
  if (!active.length) return "";
  return `<section class="panel" style="margin-bottom:22px"><div class="panel-header"><h2>Auftragswarteschlange</h2><span class="subtle-caption">Separater Worker</span></div>${table(
    ["Auftrag", "Status", "Ergebnis"],
    active.map(
      (c) =>
        `<tr><td><strong>${esc(kindLabel(c.kind))}</strong><div class="cell-sub">${esc(ago(c.created))}</div></td><td>${badge(c.state)}</td><td><span class="truncate">${esc(c.error || (c.state === "QUEUED" ? "Wartet auf den Worker" : c.state === "RUNNING" ? "Wird ausgeführt" : "Zustand vor Wiederaufnahme prüfen"))}</span></td></tr>`,
    ),
  )}</section>`;
}
function getFileParams() {
  const f = state.filters,
    p = new URLSearchParams({ limit: "50", offset: String(state.offset) });
  for (const [k, v] of Object.entries(f))
    if (v !== "" && v !== false && v != null) p.set(k, String(v));
  return p;
}
function selectionBar() {
  return state.selection.size
    ? `<div class="selection-bar"><span>${num(state.selection.size)} Dateien ausgewählt · ${bytes([...state.selection.values()].reduce((a, b) => a + b.size, 0))}</span><div class="button-row"><button class="button small" id="clear-selection">Aufheben</button><a href="#restore" class="button primary small">${icon("restore")}Wiederherstellen</a></div></div>`
    : "";
}

export {
  jobProgress,
  paintIcons,
  toast,
  heading,
  linkButton,
  empty,
  note,
  progress,
  modal,
  closeModal,
  sourceName,
  mediaName,
  mediaOptions,
  table,
  pipeline,
  storageCard,
  sparkline,
  eventLabel,
  queuePanel,
  getFileParams,
  selectionBar,
};
