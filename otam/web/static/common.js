import { localeTag, translate } from "./i18n.js";
const $ = (s, r = document) => r.querySelector(s),
  $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
// getRandomValues remains available on explicitly configured internal HTTP origins.
const newId = () => {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const value = crypto.getRandomValues(new Uint8Array(16));
  value[6] = (value[6] & 15) | 64;
  value[8] = (value[8] & 63) | 128;
  const hex = Array.from(value, (v) => v.toString(16).padStart(2, "0")).join(
    "",
  );
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};
const short = (v) => String(v || "").slice(0, 8);
const bytes = (n, prec = 1) => {
  n = Number(n || 0);
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"],
    i = Math.min(4, Math.floor(Math.log(n) / Math.log(1000)));
  return `${(n / 1000 ** i).toLocaleString(localeTag(), { maximumFractionDigits: prec })} ${u[i]}`;
};
const num = (n) => Number(n || 0).toLocaleString(localeTag());
const date = (n) =>
  n
    ? new Date(n * 1000).toLocaleString(localeTag(), {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : translate("Noch nicht");
const ago = (n) => {
  if (!n) return translate("Noch nicht");
  let s = Math.max(0, Date.now() / 1000 - n);
  return s < 60
    ? translate("gerade eben")
    : s < 3600
      ? translate(`vor ${Math.floor(s / 60)} Min.`)
      : s < 86400
        ? translate(`vor ${Math.floor(s / 3600)} Std.`)
        : date(n);
};
const labels = {
  VERIFIED: "Verifiziert",
  PREPARING: "Testdaten vorbereiten",
  ERASING: "Löschen",
  ERASE_COMMAND_COMPLETED: "Löschkommando abgeschlossen",
  NOT_STARTED: "Nicht gestartet",
  STARTING: "Wird gestartet",
  "tape-maintenance": "Bandwartung",
  UNCHANGED: "Unverändert",
  DISABLED: "Deaktiviert",
  ACTIVE: "Aktiv",
  UPDATED: "Konfiguriert",
  REMOVED: "Entfernt",
  INITIALIZED: "Freigegeben",
  PARTIAL: "Teilweise fehlgeschlagen",
  PLANNED: "Geplant",
  STAGED: "Vorbereitet",
  WAITING_MEDIA: "Medienwechsel erforderlich",
  RUNNING: "In Bearbeitung",
  PLANNING: "Inventarisierung",
  FAILED: "Fehlgeschlagen",
  INTERRUPTED: "Unterbrochen",
  INCOMPLETE: "Unvollständig",
  SUSPECT: "Fehlerverdächtig",
  READY: "Einsatzbereit",
  IN_USE: "In Verwendung",
  QUEUED: "Wartend",
  SUCCEEDED: "Abgeschlossen",
  CANCELLED: "Abgebrochen",
  FULL: "Voll",
  ARCHIVED: "Schreibgeschützt",
  UNKNOWN: "Unbekannt",
  RETIRED: "Ausgemustert",
  TESTING: "In Prüfung",
  COMPLETE: "Abgeschlossen",
  PENDING: "Ausstehend",
  WRITING: "Schreiben",
  INVENTORY: "Inventar",
  STAGING: "Staging",
  VALIDATION: "Validierung",
  TAPE_WRITE: "Schreiben",
  TAPE_READBACK: "Rücklesen",
  READBACK_POSITIONING: "Zur Rücklesung positionieren",
  STAGING_CLEANUP: "Bereinigt",
};
const badge = (s) =>
  `<span class="badge ${["VERIFIED", "SUCCEEDED", "READY", "COMPLETE"].includes(s) ? "good" : ["RUNNING", "PLANNING", "WRITING", "IN_USE"].includes(s) ? "running" : ["FAILED", "INTERRUPTED", "INCOMPLETE", "SUSPECT"].includes(s) ? "bad" : ["PLANNED", "STAGED", "QUEUED", "WAITING_MEDIA"].includes(s) ? "blue" : "neutral"}">${esc(labels[s] || s || "Unbekannt")}</span>`;
const kindLabel = (k) =>
  ({
    archive: "Archivierung",
    "archive-set": "Mehrbandarchivierung",
    plan: "Archiv planen",
    stage: "Staging vorbereiten",
    backup: "Archivieren",
    "backup-set": "Nächstes Medium archivieren",
    verify: "Integritätsprüfung",
    restore: "Wiederherstellung",
    rebuild: "Katalog rekonstruieren",
    recover: "Abbruchzustand prüfen",
    sync: "Katalog synchronisieren",
    "hardware-scan": "Status und Diagnose abfragen",
    "tape-maintenance": "Bandwartung",
    "staging-speedtest": "Staging-Speedtest",
    "create-medium": "Testmedium erstellen",
  })[k] || k;
const titles = {
  dashboard: "Übersicht",
  planning: "Planung",
  staging: "Staging",
  jobs: "Archivierungsjobs",
  catalog: "Dateikatalog",
  archives: "Archivübersicht",
  media: "Bandinventar",
  restore: "Wiederherstellen",
  integrity: "Integritätsprüfungen",
  sync: "Synchronisation",
  hardware: "Hardwarestatus",
  logs: "Protokolle",
  settings: "Einstellungen",
};

export {
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
};
