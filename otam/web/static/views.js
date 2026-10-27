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
import { getLanguage, localeTag, translate } from "./i18n.js";
import {
  paintIcons,
  toast,
  heading,
  linkButton,
  empty,
  note,
  progress,
  jobProgress,
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
} from "./ui.js";
import { api } from "./api.js";
async function dashboard() {
  const html=await dashboardBase();
  if (state.node.role !== "archive") return html;
  const jobs=(await api("/jobs")).items.filter(j=>!j.parent_job && ["RUNNING","WAITING_MEDIA","PLANNED","STAGED"].includes(j.state));
  const j=jobs.find(j=>j.state === "RUNNING") || jobs.find(j=>j.state === "WAITING_MEDIA") || jobs[0];
  if (!j) return html;
  return `<section class="panel current-plan"><div class="panel-header"><h2>Aktueller Archivplan</h2>${badge(j.state)}</div><p>${esc(kindLabel(j.kind))} · <span class="mono">${esc(short(j.id))}</span></p>${jobProgress(j.progress)}<div class="button-row"><button class="button" data-job="${esc(j.id)}">Plan und nächste Schritte</button>${j.kind === "archive-set" && ["PLANNED","WAITING_MEDIA"].includes(j.state) ? `<button class="button primary" data-backup-set="${esc(j.id)}">Archivierung für nächstes Medium bestätigen</button>` : ""}</div></section>` + html;
}
async function dashboardBase() {
  const [staging, events, driveStatus] = await Promise.all([
    api("/staging"),
    api("/events?limit=60"),
    state.node.role === "archive"
      ? api("/hardware/status")
      : Promise.resolve(null),
  ]);
  const o = state.overview,
    n = state.node,
    active =
      staging.items.find((s) => s.job_state === "RUNNING") || staging.items[0],
    transfer = events.items.filter((e) => e.event === "io_progress"),
    latest = transfer[0];
  const ready = staging.items.filter((s) => s.phase === "READY").length,
    replica = n.role === "catalog";
  const stats = [
    [
      "shield",
      "Verifiziertes Archiv",
      bytes(o.verified_bytes),
      `${num(o.verified_count)} Archive vollständig geprüft`,
      "archives",
    ],
    [
      "file",
      "Dateien im Katalog",
      num(o.file_count),
      "Jede Archivkopie einzeln erfasst",
      "catalog",
    ],
    [
      "tape",
      "Inventarisierte Medien",
      num(o.media_count),
      "Mit eindeutiger Medien-ID",
      "media",
    ],
    [
      "layers",
      replica ? "Katalogstand" : "Vorbereitete Archive",
      replica ? (n.snapshot ? `#${n.snapshot.sequence}` : "—") : num(ready),
      replica
        ? n.snapshot
          ? ago(n.snapshot.created)
          : "Synchronisation einrichten"
        : "Lokal geprüft und bereit",
      replica ? "sync" : "staging",
    ],
  ];
  const activeHtml = active
    ? `<div class="panel-body"><div class="archive-current"><div class="file-tile">${icon("archive")}</div><div><strong>Archiv ${esc(short(active.archive_id))}</strong><small>Job ${esc(short(active.job_id))} · ${esc(labels[active.phase] || active.phase)}</small></div>${badge(active.state)}</div><div class="progress-meta"><span>${bytes(active.progress_bytes)} / ${bytes(active.total_bytes)}</span><strong>${Math.min(100, Math.round((active.progress_bytes / Math.max(1, active.total_bytes)) * 100))}%</strong></div>${progress((active.progress_bytes / Math.max(1, active.total_bytes)) * 100)}${pipeline(active.phase)}<div class="throughput"><div class="throughput-number"><small>Letzter Transfer</small><strong>${latest ? bytes(latest.details.bytes_per_second) : "—"}</strong><span>${latest ? "/s" : ""}</span></div>${sparkline(transfer)}</div></div>`
    : empty(
        "Bereit für dein nächstes Archiv",
        "Wähle eine Quelle, prüfe den Plan und bereite deine TAR-Archive lokal vor.",
        "layers",
        replica
          ? linkButton("Dateikatalog öffnen", "catalog", "search")
          : linkButton("Archivierung planen", "planning", "plus", true),
      );
  const recentRows = o.recent.map(
    (a) =>
      `<tr><td><div class="table-primary"><span class="table-icon">${icon("archive")}</span><div><strong>Archiv ${esc(short(a.id))}</strong><div class="cell-sub">${esc(date(a.created))}</div></div></div></td><td>${esc(a.label)}</td><td>${bytes(a.bytes)}</td><td>${badge(a.state)}</td></tr>`,
  );
  const activities = events.items
    .filter((e) =>
      ["job_finished", "plan_ready", "confirmed", "job_created"].includes(
        e.event,
      ),
    )
    .slice(0, 4)
    .map(
      (e) =>
        `<div class="activity-item"><div class="activity-icon">${icon(e.level === "ERROR" ? "info" : e.event === "job_finished" ? "check" : "activity")}</div><div class="activity-copy"><strong>${esc(eventLabel(e))}</strong><p>Job ${esc(short(e.job_id))}${e.details.error ? " · " + esc(e.details.error) : ""}</p></div><span class="activity-time">${esc(ago(e.time))}</span></div>`,
    )
    .join("");
  return (
    heading(
      replica ? "Dein Archiv. Jederzeit im Blick." : "Alles an seinem Platz.",
      replica
        ? "Dateien finden – unabhängig vom Bandserver."
        : "Plane, sichere und finde, was dir wichtig ist.",
      replica
        ? linkButton("Dateikatalog öffnen", "catalog", "search", true)
        : linkButton("Archivierung planen", "planning", "plus", true),
    ) +
    `<div class="stats">${stats.map(([ic, title, value, foot, destination]) => `<a class="stat stat-link" href="#${destination}"><div class="stat-top"><span class="stat-title">${esc(title)}</span><span class="stat-icon">${icon(ic)}</span></div><div class="stat-value">${esc(value)}</div><div class="stat-foot ${ic === "shield" ? "positive" : ""}">${ic === "shield" ? icon("check") : ""}${esc(foot)}</div></a>`).join("")}</div>${driveStatus ? driveStatusPanel(driveStatus) : ""}<div class="dashboard-grid"><div class="main-column"><section class="panel"><div class="panel-header"><div><h2>Archivierungsablauf</h2><p>Vom lokalen Staging bis zur geprüften Kopie</p></div>${active ? `<button class="button subtle" data-job="${esc(active.job_id)}">Job ansehen ${icon("arrow")}</button>` : badge("READY")}</div>${activeHtml}</section><section class="panel"><div class="panel-header"><h2>Zuletzt archiviert</h2><a class="button subtle" href="#archives">Alle Archive ${icon("arrow")}</a></div>${table(["Archiv", "Medium", "Größe", "Status"], recentRows, "Dein erstes Archiv wartet")}<div class="panel-bottom"><span>${num(o.archive_count)} Archive im Katalog</span><span>SHA-256 · Offenes TAR-Format</span></div></section><section class="panel"><div class="panel-header"><h2>Letzte Aktivitäten</h2><a class="button subtle" href="#logs">Alle Protokolle ${icon("arrow")}</a></div>${activities ? `<div class="activity-list">${activities}</div>` : empty("Noch keine Aktivitäten", "Abgeschlossene und fehlgeschlagene Schritte werden dauerhaft protokolliert.", "activity", "", true)}</section></div><aside class="side-column">${storageCard(staging.storage)}<section class="panel info-card"><h2>Dein Archivsystem</h2><div class="node-detail"><div class="node-detail-icon">${icon("server")}</div><div><strong>${esc(n.name)}</strong><small>${replica ? "Eigenständiger Katalogdienst" : n.operation_mode === "physical" ? (n.capabilities.physical_tape ? "Archive Node · physische Archivierung" : "Archive Node · physische Wartung") : "Archive Node · Simulatorbetrieb"}</small></div><span class="status-dot"></span></div>${!replica ? `<div class="node-detail"><div class="node-detail-icon">${icon("activity")}</div><div><strong>Auftragsworker</strong><small>${Date.now() / 1000 - n.worker_heartbeat < 20 ? "Verbunden · " + esc(ago(n.worker_heartbeat)) : "Kein aktuelles Lebenszeichen"}</small></div><span class="status-dot ${Date.now() / 1000 - n.worker_heartbeat < 20 ? "" : "off"}"></span></div>` : ""}<div class="node-detail"><div class="node-detail-icon">${icon("sync")}</div><div><strong>${replica ? "Letzter empfangener Stand" : "Katalog-Synchronisation"}</strong><small>${replica ? (n.snapshot ? esc(ago(n.snapshot.created)) : "Noch nicht empfangen") : n.last_push ? esc(ago(n.last_push.time)) : "Noch nicht synchronisiert"}</small></div></div><div class="node-detail"><div class="node-detail-icon">${icon("shield")}</div><div><strong>Verifikation vor Erfolg</strong><small>Vollständiges Rücklesen · SHA-256</small></div></div></section>${note(replica ? "Dieser Katalog zeigt den letzten empfangenen Stand. Änderungen am ausgeschalteten Bandserver sind hier noch nicht enthalten." : n.operation_mode === "physical" ? (n.capabilities.physical_tape ? "Physische Archivierung ist administrativ freigegeben. Initialisierung erfolgt niemals automatisch." : "Physischer Wartungsbetrieb. Reguläre Archivierung auf echte Bänder wartet auf die Bandformat-Abnahme.") : "Simulatorbetrieb: Der Archivierungsablauf ist nutzbar. Reale LTO-Schreibzugriffe warten auf die Testband-Abnahme.", "info")}</aside></div>`
  );
}
async function planning() {
  const jobs = (await api("/jobs")).items.filter((j) =>
    j.kind === "source-plan" || j.kind === "archive-set" || (j.kind === "archive" && !j.parent_job));
  return (
    heading(
      "Gut geplant. Sicher archiviert.",
      "Wähle Quelle und Staging für den vollständigen Archivplan.",
      `<button class="button" id="new-source">${icon("folder")}Quelle hinzufügen</button>`,
    ) +
    `${state.node.operation_mode === "physical" && !state.node.capabilities.physical_tape ? note("Für Simulator-Archivierungen zuerst unter Hardware in den Simulatorbetrieb wechseln. Physische Archivierung wartet auf Bandformat-Abnahme.", "warning") : ""}<div class="split"><section class="panel"><div class="panel-header"><div><h2>Neue Archivierung planen</h2><p>Quelldaten bleiben vollständig erhalten.</p></div><span class="badge neutral">01 / PLANUNG</span></div><div class="panel-body"><form id="plan-form"><div class="form-grid"><label class="full">Datenquelle<select name="source_id" required><option value="">Quelle auswählen</option>${state.node.sources.map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("")}</select><small class="hint">Nur serverseitig freigegebene Verzeichnisse stehen zur Auswahl.</small></label><div class="full"><button class="button" type="button" id="choose-source-files">${icon("folder")}Dateien und Ordner auswählen</button><small class="hint" id="source-selection-summary">Gesamtes Quellverzeichnis (rekursiv)</small></div><label>Staging-Verzeichnis<select name="staging_id" required>${(state.node.staging_locations || []).map((r) => `<option value="${esc(r.id)}">${esc(r.label)} · ${esc(r.path)}</option>`).join("")}</select></label><div class="full">${note("Zuerst Quelle und TAR-Bedarf planen. Zielmedien wählst du anschließend im gespeicherten Quellenplan aus. Dafür muss keine Kassette eingelegt sein.", "info")}</div><label class="full">Ausgeschlossene Pfade (optional)<textarea name="excluded_paths" rows="2" placeholder="LP Archiv/.@__thumb"></textarea><small class="hint">Ein exakter Pfad je Zeile, relativ zur Quelle; Unterordner sind eingeschlossen. Keine Platzhalter.</small></label><label>Symbolische Verknüpfungen<select name="symlink_policy"><option value="skip">Überspringen und anzeigen</option><option value="error">Planung anhalten</option></select><small class="hint">Herstellerunabhängig: Verknüpfungen werden niemals verfolgt. Übersprungene Pfade erscheinen im Quellenplan.</small></label><label>Sicherungsumfang<select name="backup_mode"><option value="full">Alle ausgewählten Dateien</option><option value="additive">Additiv: nur neue Dateien</option></select><small class="hint">Abgleich mit VERIFIED-Archiven derselben Quelle und Betriebsart. Bekannte Inhalte werden nicht erneut gehasht.</small></label><label>Im additiven Modus: geänderte Dateien<select name="changed_policy"><option value="skip">Anzeigen und überspringen</option><option value="include">Als neue Version sichern (additiv)</option></select><small class="hint">Erkennung über Größe und Änderungszeit. Bei gleichen Metadaten können Inhaltsänderungen unbemerkt bleiben.</small></label><label>TAR-Zielgröße in GB<input name="target" type="number" min="0.001" max="10000" step="0.001" value="75" required><small class="hint">Große Einzeldateien bleiben zusammen.</small></label><label>Verifikation<select name="verify_mode"><option value="archive">Nach jedem TAR zurücklesen</option><option value="media">Nach allen TARs auf diesem Medium zurücklesen</option></select><small class="hint">Die zweite Option benötigt lokalen Platz für alle TARs dieses Mediums.</small></label></div><div class="form-actions"><button class="button primary" type="submit">${icon("calendar")}Quellenumfang ermitteln</button></div></form></div></section><div class="stack"><section class="panel"><div class="panel-header"><h2>Ein Plan, acht sichere Schritte.</h2></div><div class="panel-body">${pipeline("INVENTORY")}<p class="subtle-caption" style="margin-top:22px">OTAM ermittelt zuerst Dateigrößen und TAR-Bedarf ohne Inhaltslesung. Danach wählst du genügend Zielmedien. Erst bei ausreichender Kapazität folgen SHA-256 und der verbindliche Archivplan.</p></div></section>${!state.media.length ? note(state.node.operation_mode === "physical" ? "Unter Hardware ein vorhandenes OTAM-Medium registrieren oder eine neue Kassette ausdrücklich vorbereiten." : "Für den ersten vollständigen Testzyklus ein Simulatormedium im Bandinventar erstellen.", "info") : ""}${!state.node.sources.length ? note("Noch keine Quelle freigegeben. Über „Quelle hinzufügen“ ein Serververzeichnis auswählen.", "warning") : ""}</div></div><section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Deine Archivpläne</h2><span class="subtle-caption">${jobs.length} Jobs</span></div>${table(
      ["Plan", "Medium", "Erstellt", "Status", ""],
      jobs.map(
        (j) =>
          `<tr><td><strong>Archivierung ${esc(short(j.id))}</strong></td><td>${esc(j.label || (j.kind === "source-plan" ? "Noch nicht zugeordnet" : j.kind === "archive-set" ? "Mehrere Medien" : "—"))}</td><td>${esc(date(j.created))}</td><td>${badge(j.kind === "source-plan" && j.state === "WAITING_MEDIA" ? "MEDIA_SELECTION" : j.state)}</td><td><button class="button small" data-job="${esc(j.id)}">${j.kind === "source-plan" && j.state === "WAITING_MEDIA" ? "Zielmedien auswählen" : "Plan prüfen"}</button></td></tr>`,
      ),
      "Noch kein Archivplan",
    )}</section>`
  );
}
async function stagingPage() {
  const [result, speed] = await Promise.all([
    api("/staging"),
    state.node.role === "archive" ? api("/staging/speedtests") : Promise.resolve({ items: [], progress: {} }),
  ]);
  const rows = result.items;
  const locations = (result.locations || []).filter((r) => r.kind === "staging");
  const profiles = speed.drive_profiles || [];
  state.transferProfiles = profiles;
  const activePaths = new Set(locations.map((r) => r.path));
  const speedRows = speed.items.filter((r) => activePaths.has(r.storage?.path)).slice(0, 6).map((r) =>
    `<tr><td>${esc(r.time ? date(r.time) : "—")}</td><td>${esc(r.storage?.path || "—")}</td><td>${r.average_rate ? bytes(r.average_rate) + "/s" : "—"}</td><td>${r.minimum_sample_rate ? bytes(r.minimum_sample_rate) + "/s" : "—"}</td><td>${r.buffer_model ? bytes(r.buffer_model.maximum_buffer_deficit_bytes) + " / " + bytes(r.buffer_model.buffer_bytes) : "—"}</td><td>${r.average_system_cpu_percent === undefined ? "—" : r.average_system_cpu_percent.toFixed(1) + "%"}</td><td>${r.peak_io_wait_percent === undefined ? "—" : r.peak_io_wait_percent.toFixed(1) + "%"}</td><td>${r.qualified ? badge("VERIFIED") : "Nicht qualifiziert"}</td></tr>`,
  );
  const runningTests = locations.map((r) => ({ label: r.label, data: speed.progress[r.id] }))
    .filter((r) => r.data?.state === "RUNNING");
  const transferForms = locations.map((location) => {
    const sameStorage = (left, right) => left && right && ["mount", "source", "device", "type"].every((key) => left[key] === right[key]);
    const measured = speed.items.find((r) => r.storage?.path === location.path && sameStorage(r.storage, location.storage) && r.transfer_recommendation);
    const suggestion = measured?.transfer_recommendation;
    const savedValue = speed.settings?.[location.id];
    const profile = profiles.find((p) => p.drive_id === savedValue?.drive_id && p.profile_id === savedValue?.profile_id) || profiles[0];
    const saved = sameStorage(savedValue?.storage, location.storage) && savedValue?.drive_id === profile?.drive_id && savedValue?.profile_id === profile?.profile_id ? savedValue : null;
    const steps = profile?.speed_steps_bytes_per_second || [];
    const suitable = steps.filter((value) => value <= (suggestion?.write_rate_bytes_per_second || 0));
    const recommendedRate = suitable[suitable.length - 1] || steps[0] || 0;
    const rate = saved?.write_rate_bytes_per_second || recommendedRate;
    const buffer = saved?.buffer_bytes || suggestion?.buffer_bytes || 0;
    return `<form class="transfer-form" data-staging="${esc(location.id)}"><h3>${esc(location.label)}</h3>
      <p class="hint">${savedValue && !saved ? "<span>Gespeicherte Werte müssen für dieses Laufwerk und Dateisystem neu geprüft werden.</span> " : ""}${suggestion ? `Messvorschlag: ${bytes(suggestion.write_rate_bytes_per_second)}/s · ${bytes(suggestion.buffer_bytes)} Puffer${measured.qualified ? "" : " · Messung nicht qualifiziert"}` : "Noch kein Messvorschlag für dieses Staging."}</p>
      ${!profile ? "<p class=\"hint\">Kein aktuell erkanntes Laufwerk mit bestätigtem Geschwindigkeitsprofil. Hardwarestatus aktualisieren.</p>" : ""}
      ${suggestion && steps.length && suggestion.write_rate_bytes_per_second < steps[0] ? "<p class=\"error-text\">Der Messvorschlag liegt unter der niedrigsten Laufwerksstufe.</p>" : ""}
      <div class="form-grid">
        <label>Bandlaufwerk<select name="drive_id" ${profile ? "" : "disabled"} required>${profiles.map((p) => `<option value="${esc(p.drive_id)}" ${p.drive_id === profile?.drive_id ? "selected" : ""}>${esc(p.vendor)} ${esc(p.model)} · ${esc(p.drive_serial)}</option>`).join("")}</select></label>
        <label>Ziel-Datenrate zum Band (MB/s)<select name="rate_mbps" ${profile ? "" : "disabled"} required>${steps.map((value) => `<option value="${value / 1e6}" ${value === rate ? "selected" : ""}>${value / 1e6} MB/s</option>`).join("")}</select></label>
        <label>mbuffer-Größe (MiB)<input name="buffer_mib" type="number" min="256" max="4096" step="64" value="${buffer ? Math.round(buffer / 1048576) : ""}" required></label>
      </div><p class="hint">Das Laufwerk wählt seine Bandgeschwindigkeit selbst. Die Auswahl ist ein geplanter Grenzwert für den Host-Datenstrom.</p>
      <div class="form-actions"><button class="button" type="submit" ${profile ? "" : "disabled"}>Transferwerte speichern</button></div></form>`;
  }).join("");
  const speedtestPanel = state.node.role === "archive" ? `
    <section class="panel" style="margin-bottom:22px">
      <div class="panel-header"><div><h2>Staging-Speedtest</h2><p>Lokale Platte und Systemlast über längere Zeit messen.</p></div></div>
      <div class="panel-body">
        <p>OTAM erzeugt eine eigene 12-GiB-Testdatei, schreibt sie vollständig auf das gewählte Staging-Dateisystem, liest sie mit Linux O_DIRECT und entfernt ausschließlich diese Testdatei wieder. Die Bandhardware bleibt unberührt.</p>
        <form id="speedtest-form"><div class="form-grid">
          <label>Staging-Verzeichnis<select name="staging_id" required>${locations.filter((r) => r.available && r.writable && r.storage?.local).map((r) => `<option value="${esc(r.id)}">${esc(r.label)} · ${esc(r.path)}</option>`).join("")}</select></label>
          <label>Messdauer<select name="seconds"><option value="1800">30 Minuten · Qualifikation</option><option value="60">1 Minute · Funktionstest</option></select></label>
        </div><p class="hint">Qualifiziert wird nur ein vollständiger 30-Minuten-Lauf mit mindestens 10 GiB Testdatei. Für 120 MB/s muss der Durchschnitt mindestens 5 % Reserve haben; gemessene Einbrüche müssen mit dem vorgeschlagenen Puffer samt Reserve überbrückt und bis Testende aufgeholt werden. CPU-Auslastung und I/O-Wartezeit werden mitprotokolliert.</p>
        <div class="form-actions"><button class="button primary" type="submit" ${locations.some((r) => r.available && r.writable && r.storage?.local) ? "" : "disabled"}>Speedtest starten</button></div></form>
        ${runningTests.map((r) => `<div class="progress-meta"><span>${esc(r.label)} · ${r.data.phase === "PREPARING" ? "Testdatei vorbereiten" : "Direkt lesen"}</span><strong>${r.data.bytes_per_second ? bytes(r.data.bytes_per_second) + "/s" : bytes(r.data.bytes || 0)}</strong></div>${progress(r.data.phase === "PREPARING" ? 100 * (r.data.bytes || 0) / Math.max(1, r.data.total_bytes || 1) : 100 * (r.data.elapsed || 0) / Math.max(1, r.data.duration || 1))}<p class="hint">CPU ${(r.data.system_cpu_percent || 0).toFixed(1)} % · I/O-Wartezeit ${(r.data.io_wait_percent || 0).toFixed(1)} % · Last ${(r.data.load1 || 0).toFixed(2)}</p>`).join("")}
      </div>
      ${table(["Zeit", "Staging", "Durchschnitt", "Minimum", "Pufferdefizit / Größe", "CPU Ø", "I/O-Wait max.", "Ergebnis"], speedRows, "Noch kein Speedtest durchgeführt")}
      <div class="panel-body"><h3>Transferwerte</h3><p class="hint">${state.node.capabilities.physical_tape ? "Gespeicherte Transferwerte werden vor jedem physischen Schreibjob erneut geprüft und für diesen Job angewandt." : "Die Vorschläge berücksichtigen gemessene Leserate und verfügbaren RAM. Gespeicherte Werte sind bis zur Freigabe des physischen Schreibpfads noch nicht wirksam."}</p>${transferForms}</div>
    </section>` : "";
  return (
    heading(
      "Vorbereitet für den langen Weg.",
      "Vollständige lokale TARs. Erst geprüft, dann zum Band.",
      `<button class="button primary" id="new-staging">${icon("layers")}Staging hinzufügen</button>`,
    ) +
    `<section class="panel" style="margin-bottom:22px"><div class="panel-header"><h2>Staging-Verzeichnisse</h2></div>${resourceTable(locations)}</section>${speedtestPanel}<div class="dashboard-grid"><div class="main-column">${rows.length ? rows.map((s) => `<section class="panel job-card"><div class="job-top"><div><strong>Archiv ${esc(short(s.archive_id))}</strong><small>Job ${esc(short(s.job_id))} · ${esc(ago(s.updated))}</small></div>${badge(s.state)}</div><div class="progress-meta"><span>${esc(labels[s.phase] || s.phase)}</span><strong>${bytes(s.progress_bytes)} / ${bytes(s.total_bytes)}</strong></div>${progress((s.progress_bytes / Math.max(1, s.total_bytes)) * 100)}${pipeline(s.phase)}${s.error ? `<p class="error-text">${esc(s.error)}</p>` : ""}<div class="button-row"><button class="button small" data-job="${esc(s.job_id)}">Job und Plan ansehen ${icon("arrow")}</button></div></section>`).join("") : `<section class="panel">${empty("Noch keine Archive im Staging", "Erstelle einen Plan und starte die lokale Vorbereitung.", "layers", state.node.role === "archive" ? linkButton("Planung öffnen", "planning", "calendar", true) : "")}</section>`}</div><aside class="side-column">${storageCard(result.storage)}${note("Staging-Archive bleiben bis zur erfolgreichen Rückleseverifikation erhalten. Nur von OTAM verwaltete temporäre Dateien werden danach bereinigt.")}</aside></div>`
  );
}
async function jobsPage() {
  const jobs = (await api("/jobs")).items.filter((j) => !j.parent_job);
  return (
    heading(
      "Jeder Schritt nachvollziehbar.",
      "Archivierungsjobs und ihre dauerhaft gespeicherten Ergebnisse.",
    ) +
    queuePanel() +
    `<section class="panel"><div class="panel-header"><h2>Archiv- und Prüfjobs</h2><span class="subtle-caption">${num(jobs.length)} zuletzt angelegte Jobs</span></div>${table(
      ["Job", "Medium", "Phase", "Status", "Aktualisiert", ""],
      jobs.map(
        (j) =>
          `<tr><td><strong>${esc(kindLabel(j.kind))}</strong><div class="cell-sub mono">${esc(short(j.id))}</div></td><td>${esc(j.label || "—")}</td><td>${j.progress ? jobProgress(j.progress) : esc(labels[j.phase] || j.phase || "—")}</td><td>${badge(j.kind === "source-plan" && j.state === "WAITING_MEDIA" ? "MEDIA_SELECTION" : j.state)}</td><td>${esc(ago(j.updated))}</td><td><button class="button small" data-job="${esc(j.id)}">Details ${icon("arrow")}</button></td></tr>`,
      ),
      "Noch keine Jobs",
    )}</section>`
  );
}
async function archivesPage() {
  const r = await api("/archives?limit=200");
  return (
    heading(
      "Deine Archive im Überblick.",
      "Jedes Archiv mit Medienposition, Prüfsumme und Verifikationsstatus.",
    ) +
    `<section class="panel"><div class="panel-header"><h2>Archivbestand</h2><a class="button small" href="/api/v1/export?table=archives&format=json">${icon("download")}JSON exportieren</a></div>${table(
      ["Archiv", "Medium / Position", "Dateien", "Größe", "Status", ""],
      r.items.map(
        (a) =>
          `<tr><td><strong>${esc(short(a.id))}</strong><div class="cell-sub mono" title="${esc(a.sha256)}">SHA-256 ${esc(short(a.sha256))}…</div></td><td>${esc(a.label)}<div class="cell-sub">Banddatei ${num(a.tape_file)}</div></td><td>${num(a.file_count)}</td><td>${bytes(a.bytes)}</td><td>${badge(a.state)}</td><td><button class="button small" data-archive-files="${esc(a.id)}">Dateien ${icon("arrow")}</button></td></tr>`,
      ),
      "Noch keine Archive",
    )}<div class="panel-bottom">${num(r.total)} Archive · Anzeige bis zu 200 neueste Archive</div></section>`
  );
}
async function catalogPage() {
  const r = await api("/files?" + getFileParams());
  state.files = r.items;
  const f = state.filters;
  return (
    heading(
      "Finde, was du bewahren möchtest.",
      "Dein vollständiger Dateikatalog – mit allen Archivkopien.",
      `<a class="button" href="/api/v1/export?table=files&format=csv">${icon("download")}Katalog exportieren</a>`,
    ) +
    `<div id="selection-bar">${selectionBar()}</div><section class="panel"><form id="catalog-form"><div class="search-toolbar"><div class="search-input">${icon("search")}<input name="q" aria-label="Dateiname oder Pfad suchen" placeholder="Dateiname oder Pfad suchen …" value="${esc(f.q || "")}"></div><select name="file_type" aria-label="Dateityp"><option value="">Alle Dateitypen</option>${[".jpg", ".png", ".pdf", ".mp4", ".txt", ".tar", ".json", ".raw"].map((x) => `<option ${f.file_type === x ? "selected" : ""} value="${x}">${x.toUpperCase().slice(1)}</option>`).join("")}</select><select name="media_id" aria-label="Medium"><option value="">Alle Medien</option>${state.media.map((m) => `<option value="${esc(m.id)}" ${f.media_id === m.id ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select><button type="button" class="button" id="filter-toggle" aria-expanded="${state.advanced}">${icon("filter")}Filter</button><button class="button primary" type="submit">Suchen</button></div><div class="advanced-filters" ${state.advanced ? "" : "hidden"}><label>SHA-256<input name="checksum" value="${esc(f.checksum || "")}" placeholder="Exakte Prüfsumme" maxlength="64"></label><label>Mindestgröße (MB)<input name="min_mb" type="number" min="0" step="0.001" value="${f.min_size ? Number(f.min_size) / 1e6 : ""}"></label><label>Maximalgröße (MB)<input name="max_mb" type="number" min="0" step="0.001" value="${f.max_size ? Number(f.max_size) / 1e6 : ""}"></label><label>Status<select name="state"><option value="">Alle Zustände</option>${["VERIFIED", "SUSPECT", "INCOMPLETE", "WRITING"].map((s) => `<option value="${s}" ${f.state === s ? "selected" : ""}>${esc(labels[s])}</option>`).join("")}</select></label><label>Geändert ab<input type="date" name="after_date" value="${esc(f.after_date || "")}"></label><label>Geändert bis<input type="date" name="before_date" value="${esc(f.before_date || "")}"></label><label class="check-label"><input type="checkbox" name="duplicates" ${f.duplicates ? "checked" : ""}>Nur exakte Dubletten</label><button type="button" class="button small" id="clear-filters">Filter zurücksetzen</button></div></form>${f.archive_id ? `<div class="selection-bar" style="margin:15px">Dateien von Archiv ${esc(short(f.archive_id))}<button class="button small" id="clear-filters">Alle Archive</button></div>` : ""}${table(
      [
        '<input type="checkbox" id="select-page" aria-label="Alle Dateien dieser Seite auswählen">',
        "Datei / Archivpfad",
        "Größe",
        "Geändert",
        "Medium",
        "Kopien",
        "Status",
      ],
      r.items.map(
        (v, i) =>
          `<tr><td><input type="checkbox" class="file-select" data-index="${i}" aria-label="${esc(v.path)} auswählen" ${state.selection.has(v.archive_id + ":" + v.path) ? "checked" : ""}></td><td><div class="table-primary"><span class="table-icon">${icon("file")}</span><div><strong class="truncate" title="${esc(v.path)}">${esc(v.name)}</strong><div class="cell-sub truncate">${esc(v.path)}</div></div></div></td><td>${bytes(v.size)}</td><td>${esc(date(v.mtime_ns / 1e9))}</td><td>${esc(v.label)}<div class="cell-sub">Banddatei ${v.tape_file}</div></td><td><button class="button subtle" data-copies="${esc(v.sha256)}" title="Alle Kopien anhand SHA-256 suchen">${v.copies} ${v.copies === 1 ? "Kopie" : "Kopien"}</button></td><td>${badge(v.state)}</td></tr>`,
      ),
      "Keine passenden Dateien gefunden",
    )}<div class="table-footer"><span>${num(r.total)} Treffer${r.total ? " · " + num(state.offset + 1) + "–" + num(state.offset + r.items.length) : ""}</span><div class="button-row"><button class="button small" id="prev-page" ${state.offset === 0 ? "disabled" : ""}>← Zurück</button><button class="button small" id="next-page" ${state.offset + 50 >= r.total ? "disabled" : ""}>Weiter →</button></div></div></section>`
  );
}
async function mediaPage() {
  return (
    heading(
      "Ein Platz für jedes Band.",
      "Medienidentität, Kapazität und Archivzustand im Blick.",
      state.node.role === "archive"
        ? state.node.operation_mode === "physical"
          ? linkButton("OTAM-Medium lesend registrieren", "hardware", "tape", true)
          : `<button class="button primary" id="new-medium">${icon("plus")}Testmedium erstellen</button>`
        : "",
    ) +
    (!state.media.length
      ? `<section class="panel">${empty("Noch kein Medium inventarisiert", state.node.role === "catalog" ? "Noch keine Medien im synchronisierten Katalog." : state.node.operation_mode === "physical" ? "Unter Hardware ein vorhandenes OTAM-Medium registrieren oder eine neue Kassette ausdrücklich vorbereiten." : "Erstelle ein ausdrücklich als Simulation gekennzeichnetes Testmedium für deinen ersten Archivierungszyklus.", "tape")}</section>`
      : `<div class="cards-grid">${state.media.map((m) => `<section class="panel media-card"><div class="media-top"><div class="media-illustration">${icon("tape")}</div>${badge(m.state)}</div><h2>${esc(m.label)}</h2><span class="mono">${esc(m.id)}</span><dl><div><dt>Medienklasse</dt><dd>${m.class === "permanent" ? "Dauerarchiv" : "Rotierende Sicherung"}</dd></div><div><dt>Generation</dt><dd>LTO-${num(m.generation)} · ${bytes(m.capacity)}</dd></div><div><dt>Archive</dt><dd>${num(m.archive_count)}</dd></div><div><dt>Letzte Prüfung</dt><dd>${esc(m.last_verified ? ago(m.last_verified) : "Noch nicht")}</dd></div><div><dt>Lagerort</dt><dd>${esc(m.location || "Nicht hinterlegt")}</dd></div><div><dt>Backend</dt><dd>${state.node.role === "catalog" ? "Replizierter Katalog" : m.backend === "physical" ? (m.mounted ? "Physisches Medium eingelegt" : "Physisches Medium nicht eingelegt") : m.mounted ? "Simulator eingebunden" : "Nicht eingebunden"}</dd></div></dl><div class="progress-meta"><span>${bytes(m.used)} verwendet</span><strong>${Math.round((m.used / m.capacity) * 100)}%</strong></div>${progress((m.used / m.capacity) * 100)}<div class="button-row"><button class="button small" data-media-files="${esc(m.id)}">${icon("search")}Dateien</button>${state.node.role === "archive" && m.mounted ? `<button class="button small" data-verify="${esc(m.id)}">${icon("shield")}Prüfen</button><button class="icon-button" data-medium-tools="${esc(m.id)}" aria-label="Werkzeuge für ${esc(m.label)}">⋯</button>` : ""}</div></section>`).join("")}</div>`)
  );
}
async function restorePage() {
  const selected = [...state.selection.values()],
    groups = new Map();
  for (const f of selected) {
    const key = f.media_id + ":" + f.archive_id;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(f);
  }
  const replica = state.node.role === "catalog";
  return (
    heading(
      "Deine Dateien. Wieder bei dir.",
      "Wähle Dateien im Katalog aus und prüfe den Wiederherstellungsplan.",
      linkButton("Dateien auswählen", "catalog", "search", true),
    ) +
    (replica
      ? note(
          "Die eigenständige Kataloginstanz hat keinen Zugriff auf Bandmedien. Du kannst die Auswahl als Medien- und Dateiliste herunterladen und am Bandserver verwenden.",
          "info",
        )
      : "") +
    `<div class="split" style="margin-top:20px"><section class="panel"><div class="panel-header"><div><h2>Deine Auswahl</h2><p>${num(selected.length)} Dateien · ${new Set(selected.map((f) => f.media_id)).size} benötigte Medien · ${bytes(selected.reduce((a, b) => a + b.size, 0))}</p></div></div>${
      selected.length
        ? `<div class="panel-body">${[...groups.values()]
            .map(
              (files) =>
                `<div class="job-card panel"><div class="job-top"><div><strong>${esc(files[0].label)}</strong><small>Archiv ${esc(short(files[0].archive_id))} · Banddatei ${files[0].tape_file}</small></div>${badge(files.every((f) => f.state === "VERIFIED") ? "VERIFIED" : "SUSPECT")}</div>${files
                  .slice(0, 5)
                  .map(
                    (f) =>
                      `<p class="mono truncate" title="${esc(f.path)}">${esc(f.path)}</p>`,
                  )
                  .join(
                    "",
                  )}${files.length > 5 ? `<p class="hint">und ${num(files.length - 5)} weitere Dateien</p>` : ""}<div class="button-row">${replica ? "" : `<button class="button small" data-restore-group="${esc(files[0].media_id + ":" + files[0].archive_id)}">Plan prüfen ${icon("arrow")}</button>`}</div></div>`,
            )
            .join(
              "",
            )}<button class="button" id="download-selection">${icon("download")}Auswahlliste herunterladen</button></div>`
        : empty(
            "Was möchtest du wiederherstellen?",
            "Markiere einzelne Dateien oder alle Treffer einer Katalogseite.",
            "restore",
            linkButton("Zum Dateikatalog", "catalog", "search"),
          )
    }</section><section class="panel"><div class="panel-header"><h2>Sicher zurückholen</h2></div><div class="panel-body"><div class="node-detail"><div class="node-detail-icon">${icon("tape")}</div><div><strong>Medium und Position bekannt</strong><small>Jede Datei verweist auf ihre Archivkopie.</small></div></div><div class="node-detail"><div class="node-detail-icon">${icon("shield")}</div><div><strong>Keine bestehenden Dateien überschreiben</strong><small>Jeder Restore erhält ein neues Zielverzeichnis.</small></div></div><div class="node-detail"><div class="node-detail-icon">${icon("check")}</div><div><strong>SHA-256 nach Wiederherstellung</strong><small>Erfolg erst nach Integritätsprüfung.</small></div></div>${note("Unterschiedliche Archive werden einzeln bestätigt. Geführte physische Mehrbandwechsel sind noch nicht freigegeben.", "info")}</div></section></div>`
  );
}
async function integrityPage() {
  const r = await api("/verifications");
  return (
    heading(
      "Vertrauen braucht Verifikation.",
      "Vollständiges Rücklesen statt bloßer Schreib-Erfolgsmeldung.",
    ) +
    `<section class="panel"><div class="panel-header"><h2>Prüfung starten</h2></div><div class="panel-body">${state.node.role === "archive" ? `<form id="verify-form" class="form-grid"><label>Medium<select name="media_id" required>${mediaOptions()}</select></label><div class="form-actions" style="margin-top:0;padding-top:0;border:0;align-items:end"><button class="button primary" type="submit">${icon("shield")}Vollständig verifizieren</button></div></form>` : note("Prüfungen werden auf dem Bandserver ausgeführt. Hier siehst du den letzten synchronisierten Nachweis.", "info")}</div></section><section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Verifikationshistorie</h2></div>${table(
      ["Zeitpunkt", "Archiv", "Job", "Ergebnis", "Hinweis"],
      r.items.map(
        (v) =>
          `<tr><td>${esc(date(v.time))}</td><td class="mono">${esc(short(v.archive_id) || "Gesamtes Medium")}</td><td><button class="button subtle" data-job="${esc(v.job_id)}">${esc(short(v.job_id))}</button></td><td>${badge(v.state)}</td><td>${esc(v.error || "Prüfsummen stimmen überein")}</td></tr>`,
      ),
      "Noch keine Verifikation durchgeführt",
    )}</section>`
  );
}
async function syncPage() {
  const r = await api("/replication");
  const publisher = state.node.role === "archive";
  const ts = r.targets || [];
  return (
    heading(
      "Dein Katalog. Frei vernetzt.",
      "Lokal verfügbar. Weitere Standorte bestimmst du selbst.",
      publisher
        ? `<button class="button primary" id="new-target">${icon("plus")}Ziel hinzufügen</button>`
        : "",
    ) +
    `<section class="panel"><div class="panel-header"><h2>${publisher ? "Lokaler Katalog" : "Eigenständiger Katalogdienst"}</h2><span class="badge success">${publisher ? "Fester Bestandteil" : "Lesende Kopie"}</span></div><div class="panel-body">${note(publisher ? "Der Katalog bleibt auf diesem Archive Node verfügbar. Zusätzliche Dienste, Container, Server und Sicherungsverzeichnisse sind optional. Ihr Ausfall verhindert weder die lokale Suche noch die Archivierung." : "Dieser Dienst durchsucht den zuletzt empfangenen Katalog auch bei ausgeschaltetem Archive Node. Änderungen am Archiv werden ausschließlich auf dem Archive Node vorgenommen.")}<dl class="detail-list" style="margin-top:20px"><dt>Node-ID</dt><dd class="mono">${esc(state.node.id)}</dd><dt>${publisher ? "Datenhaltung" : "Letzter Empfang"}</dt><dd>${publisher ? "Lokale SQLite-Datenbank · unabhängig von optionalen Zielen" : r.active ? esc(date(r.active.received)) + " · #" + r.active.sequence : "—"}</dd></dl></div></section>` +
    (publisher
      ? `<section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Optionale Ziele</h2><button class="button" id="sync-now" ${ts.some((t) => t.enabled) ? "" : "disabled"}>${icon("sync")}Jetzt synchronisieren</button></div>${table(
          ["Ziel", "Verbindung", "Intervall", "Übertragung", "Verwaltung"],
          ts.map(
            (t) =>
              `<tr><td><strong>${esc(t.label)}</strong><small class="hint">${t.kind === "catalog" ? "Katalogdienst mit eigener Weboberfläche" : "Geprüfte Snapshot-Dateien"}</small></td><td>${badge(t.enabled ? "ACTIVE" : "DISABLED")}<small class="hint mono">${esc(t.address)}</small></td><td>${num(t.interval)} s</td><td>${t.status ? badge(t.status.state) + `<small class="hint">${esc(date(t.status.time))}${t.status.error ? " · " + esc(t.status.error) : ""}</small>` : "Noch nicht übertragen"}</td><td><button class="button subtle" data-edit-target="${esc(t.id)}">Bearbeiten</button>${t.kind === "directory" ? `<button class="button subtle" data-init-target="${esc(t.id)}">Zielmarker</button>` : ""}<button class="button subtle" data-delete-target="${esc(t.id)}">Entfernen</button></td></tr>`,
          ),
          "Keine zusätzlichen Ziele eingerichtet. Der lokale Katalog ist vollständig nutzbar.",
        )}</section>`
      : "") +
    `<section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Übertragungsverlauf</h2><span class="badge neutral">SHA-256 + HMAC</span></div>${table(
      ["Zeit", "Richtung", "Sequenz", "Status", "Details"],
      r.events.map(
        (e) =>
          `<tr><td>${esc(date(e.time))}</td><td>${esc(e.direction)}</td><td>${e.sequence ? "#" + e.sequence : "—"}</td><td>${badge(e.state)}</td><td>${esc(e.details)}</td></tr>`,
      ),
      "Noch keine Synchronisation",
    )}</section>`
  );
}
function exactCounter(value) {
  try {
    return BigInt(value).toLocaleString(localeTag());
  } catch {
    return "Nicht verfügbar";
  }
}
function driveStatusPanel(status) {
  const observed = status.drives.filter(d => d.observed_present);
  const selected = status.current_drive || observed.find(d => d.id === status.active_maintenance?.drive_id) || observed[0];
  const cards = (selected ? [selected] : []).map((d) => {
    const current = d.contact_state === "CURRENT",
      st = d.status || {},
      diag = d.diagnostics,
      sample = diag.sample;
    const stateLabel = d.active_maintenance
      ? d.active_maintenance.fresh
        ? "Bandwartung läuft"
        : "Bandwartung · Status veraltet"
      : !current
        ? d.contact_state === "OFFLINE"
          ? "Nicht erreichbar"
          : "Status veraltet"
        : d.busy
          ? "Laufwerk belegt"
          : st.online
            ? !d.medium_serial
              ? "Medium nicht identifiziert"
              : st.write_protected
                ? "Schreibgeschützt"
                : "Medium bereit"
            : st.door_open
              ? "Kein Medium"
              : "Nicht bereit / unbekannt";
    const currentAlerts = diag.current_alerts;
    const registered = state.media.find(m => m.backend === "physical" && m.serial && m.serial === d.medium_serial);
    const medium = current ? (st.door_open ? "Kein Band eingelegt" : d.medium_serial || "Nicht identifiziert")
      : status.busy ? (d.medium_serial || "Nicht identifiziert") : "Nicht aktuell bestätigt";
    return `<article class="drive-status-card current-medium-card"><div class="current-medium-main"><div class="current-medium-icon">${icon("tape")}</div><div><span class="eyebrow">${current ? "Eingelegtes Band" : status.busy ? "Zuletzt bestätigtes Band" : "Bandstatus nicht aktuell"}</span><h3 class="mono">${esc(medium)}</h3>${current && d.medium_serial ? `<p class="hint">${registered ? `Im Bandinventar: ${esc(registered.label)}` : "Noch nicht im Bandinventar registriert"}</p>` : ""}<span class="badge ${current && st.online && d.medium_serial ? "good" : "neutral"}">${esc(stateLabel)}</span></div></div><div class="current-medium-details"><strong>${esc([d.vendor,d.model].filter(Boolean).join(" ") || d.device)}</strong><p class="hint mono">${esc(d.device)} · SN ${esc(d.serial || "nicht ermittelt")}</p><dl class="detail-list"><dt>Schreibschutz</dt><dd>${current && typeof st.write_protected === "boolean" ? (st.write_protected ? "Ja" : "Nein") : "Nicht aktuell bestätigt"}</dd><dt>Letzte Erkennung</dt><dd>${esc(date(status.last_scan || d.last_seen))}</dd></dl><p class="hint">${Array.isArray(currentAlerts) ? (currentAlerts.length ? `<span class="error-text">Aktuelle TapeAlert-Flags: ${num(currentAlerts.length)}.</span> <a href="#hardware">Diagnosedaten</a>` : "Keine aktiven TapeAlert-Flags bei aktueller Abfrage.") : "TapeAlert: aktuelle Abfrage für dieses Medium steht aus."}</p>${d.error && current ? `<p class="hint error-text">${esc(d.error)}</p>` : ""}</div></article>`;
  });
  const running = status.active_maintenance;
  const runHtml = running
    ? `<div class="panel-body"><div class="archive-current"><div class="file-tile">${icon("tape")}</div><div><strong>${esc(running.operation === "qualify-sample" ? "Begrenzter Dauertest" : running.operation)}</strong><small>Job ${esc(short(running.command_id))} · ${esc(labels[running.phase] || running.phase)} · ${esc(ago(running.time))}</small></div>${badge("RUNNING")}</div>${!running.fresh ? note("Kein aktueller Fortschritt: Worker und Verbindung prüfen. Der letzte gespeicherte Stand ist kein Nachweis für laufenden Transfer.", "warning") : ""}<div class="progress-meta"><span>${bytes(running.bytes || 0)}${running.total_bytes ? " / " + bytes(running.total_bytes) : ""}</span><strong>${running.bytes_per_second ? bytes(running.bytes_per_second) + "/s" : "Messung steht aus"}</strong></div>${running.total_bytes ? progress((100 * running.bytes) / running.total_bytes) : ""}${running.operation === "qualify-sample" ? '<p class="hint">Begrenzter Testbereich. Erfolg erst nach vollständiger Rücklesung; keine Vollqualifikation des Mediums.</p>' : ""}</div>`
    : "";
  return `<section class="panel drive-overview"><div class="panel-header"><div><h2>Aktuelles Band & Laufwerksstatus</h2><p>Aktueller Zustand · bekannte Bänder findest du im Bandinventar</p></div><a class="button subtle" href="#hardware">Diagnosedaten ${icon("arrow")}</a></div>${(status.observed_drive_count ?? observed.length) > 1 ? `<div class="panel-body"><p class="hint">${num(status.observed_drive_count ?? observed.length)} Laufwerke erkannt. Weitere Laufwerke und ihre Messwerte unter Diagnosedaten.</p></div>` : ""}${status.busy ? `<div class="panel-body">${note("Worker beschäftigt: zusätzliche Status- und Diagnoseabfragen pausieren während des Jobs. Angezeigt werden die letzten Messwerte.", "info")}</div>` : ""}${runHtml}${cards.length ? `<div class="drive-status-list">${cards.join("")}</div>` : `<div class="panel-body">${note(status.fresh ? "Kein Bandlaufwerk erreichbar. Es ist möglicherweise ausgeschaltet oder nicht verbunden." : "Noch kein aktueller Laufwerksstatus. Worker und Verbindung prüfen.", "info")}<p class="hint">Letzte Erkennung: ${esc(date(status.last_scan))} · Worker ${status.worker_online ? "verbunden" : "ohne aktuelles Lebenszeichen"}. Der Status wird automatisch aktualisiert.</p></div>`}</section>`;
}
function diagnosticDetails(status) {
  return `<section class="panel hardware-diagnostics" style="margin-top:22px"><div class="panel-header"><h2>Diagnosedaten</h2></div><div class="panel-body">${note("Nur lesende SCSI-Abfragen. TapeAlert kann beim Lesen quittiert werden; gemeldete Hinweise bleiben deshalb in OTAM gespeichert. Werte sind keine Vorhersage der verbleibenden Lebensdauer.", "info")}${
    !status.drives.length
      ? '<p class="hint">Keine Messwerte verfügbar, solange kein Laufwerk erreichbar ist.</p>'
      : status.drives
          .map((d) => {
            const sample = d.diagnostics.sample,
              pages = sample?.pages || {};
            const temperature =
              pages["0d"]?.state === "AVAILABLE"
                ? pages["0d"].decoded.current_celsius
                : null;
            const card = `<article class="diagnostic-detail"><h3>${esc([d.vendor, d.model].filter(Boolean).join(" ") || d.device)} · ${esc(d.device)}</h3><p class="hint">${sample ? `Abfrage ${esc(date(sample.time))} · Zuletzt beobachtetes Medium bei Abfrage: ${esc(sample.medium_serial || "unbekannt")}` : "Noch keine Diagnosemessung vorhanden."}${d.diagnostics.stale ? " · Messwerte sind veraltet oder nicht aktuell erreichbar." : ""}</p><dl class="detail-list"><dt>Temperatur</dt><dd>${temperature === null || temperature === undefined ? "Nicht verfügbar" : `${num(temperature)} °C`}</dd><dt>Referenztemperatur</dt><dd>${pages["0d"]?.decoded?.reference_celsius == null ? "Nicht verfügbar" : num(pages["0d"].decoded.reference_celsius) + " °C"}</dd><dt>Bandposition (letzter Status)</dt><dd>${d.status?.file_number >= 0 ? "Banddatei " + num(d.status.file_number) : "Dateiposition unbekannt"} · ${d.status?.block_number >= 0 ? "Block " + num(d.status.block_number) : "Blockposition unbekannt"}</dd></dl>${[
              ["02", "Schreibfehlerzähler"],
              ["03", "Lesefehlerzähler"],
            ]
              .map(
                ([key, label]) =>
                  `<h3>${label}</h3>${
                    pages[key]?.state === "AVAILABLE"
                      ? table(
                          ["Messwert", "Vom Laufwerk gemeldeter Wert"],
                          pages[key].decoded.counters.map(
                            (c) =>
                              `<tr><td>${esc(c.label)}</td><td class="mono">${esc(exactCounter(c.value))}${c.unit === "bytes" ? " Bytes" : ""}</td></tr>`,
                          ),
                        )
                      : `<p class="hint">Nicht verfügbar${pages[key]?.error ? ": " + esc(pages[key].error) : ""}</p>`
                  }`,
              )
              .join(
                "",
              )}<p class="hint">Laufwerkszähler sind nicht automatisch diesem Band zuzuordnen und können beim Einschalten zurückgesetzt werden. Fehlende Werte sind keine Nullwerte.</p><h3>Frühere TapeAlert-Hinweise (Verlauf)</h3>${table(
              ["Flag", "Erstmals", "Zuletzt", "Zuletzt beobachtetes Medium"],
              d.diagnostics.warning_history.map(
                (a) =>
                  `<tr><td>TapeAlert ${a.code}</td><td>${esc(date(a.first_seen))}</td><td>${esc(date(a.last_seen))}</td><td class="mono">${esc(a.medium_serial || "Unbekannt")}</td></tr>`,
              ),
              "Bisher keine auswertbaren TapeAlert-Hinweise gespeichert",
            )}<details class="diagnostic-raw" data-live-detail="raw-${esc(d.id)}"><summary>Rohdaten, Quellen und Linux-Treiberzähler anzeigen</summary><pre class="code-block">${esc(JSON.stringify(d.diagnostics, null, 2))}</pre></details></article>`;
            return d.observed_present ? card : `<details class="diagnostic-history" data-live-detail="history-${esc(d.id)}"><summary>Frühere Erkennung · ${esc(d.serial || d.device)} · ${esc(date(d.last_seen))}</summary>${card}</details>`;
          })
          .join("")
  }</div></section>`;
}
function resourceTable(items) {
  return table(
    ["Verzeichnis", "Pfad", "Speicher", "Verwaltung"],
    items.map(
      (r) =>
        `<tr><td><strong>${esc(r.label)}</strong><small class="hint">${r.kind === "source" ? "Quelle" : "Staging"}</small></td><td class="mono">${esc(r.path)}</td><td>${r.kind === "source" ? "Wird beim Zugriff geprüft" : r.available ? `${bytes(r.storage?.free)} <span>frei von</span> ${bytes(r.storage?.total)} · ${esc(r.storage?.type || "")}` : "Nicht erreichbar"}</td><td><button class="button subtle" data-remove-resource="${esc(r.id)}">Abmelden</button></td></tr>`,
    ),
    "Noch keine Verzeichnisse registriert",
  );
}
function hardwareDriveCard(d, r) {
  const actions = r.media_actions?.[d.id] || {};
  const ready = r.mode === "physical" && d.ready && d.serial && d.medium_serial && Date.now() / 1000 - r.discovery.time <= 120;
  const identity = `data-drive-serial="${esc(d.serial || "")}" data-medium-serial="${esc(d.medium_serial || "")}"`;
  const initial = actions.initialization || {enabled: false, reason: "Status & Diagnose aktualisieren"};
  const reset = actions.reset || {enabled: false, reason: ""};
  const reinit = actions.reinitialization || {enabled:false};
  const maintenanceDisabled = !ready || Date.now() / 1000 - r.discovery.time > 30;
  const registered = state.media.some(m => m.backend === "physical" && m.serial && m.serial === d.medium_serial);
  return `<article class="hardware-drive-card" data-hardware-drive="${esc(d.id)}"><div class="hardware-drive-heading"><div><h3>${esc([d.vendor, d.model].filter(Boolean).join(" "))}</h3><p class="hint mono">SN ${esc(d.serial || "unbekannt")} · ${esc(d.device)}</p></div><span class="badge neutral">${esc(d.medium_serial || "Kein identifiziertes Medium")}</span></div>
    <div class="hardware-actions"><button class="button" data-register-physical="${esc(d.id)}" ${identity} ${ready && !registered ? "" : "disabled"}>${registered ? "Bereits im Bandinventar registriert" : "OTAM-Medium lesend registrieren"}</button>${r.physical_initialization_enabled ? `<button class="button" data-initialize-physical="${esc(d.id)}" ${identity} ${ready && initial.enabled ? "" : "disabled"}>Band für OTAM vorbereiten</button>` : ""}${r.physical_reset_enabled && reset.enabled ? `<button class="button" data-reset-physical="${esc(d.id)}" ${identity} ${ready ? "" : "disabled"}>Unterbrochenes Medium zurücksetzen</button>` : ""}</div>
    ${r.physical_initialization_enabled && !initial.enabled ? `<p class="hint hardware-action-reason">Initialisierung gesperrt: ${esc(initial.reason)}</p>` : ""}
    ${reinit.enabled ? `<div class="hardware-reinitialization"><p class="hint">Diese Kassette wurde bereits initialisiert, ist aber im aktuellen Katalog nicht vorhanden. Lesend registrieren erhält die Inhalte. Neuinitialisierung macht sie unbrauchbar.</p><p class="hint mono">Frühere Medien-ID ${esc(reinit.previous_media_id)} · ${esc(date(reinit.finished))}</p><button class="button" data-reinitialize-physical="${esc(d.id)}" ${identity} ${ready ? "" : "disabled"}>Kassette ausdrücklich neu initialisieren</button></div>` : ""}
    <details class="hardware-maintenance"><summary>Bandpflege und destruktive Tests</summary><p class="hint">Diese Aktionen verändern Bandinhalte. Jeder Vorgang verlangt eine eigene Bestätigung.</p><div class="hardware-actions">${[["qualify", "Vollständig testen"], ["qualify-sample", "Begrenzter Dauertest"], ["erase-short", "Kurz löschen"], ["erase-long", "Lang löschen"]].map(([op, label]) => `<button class="button" data-maintenance-drive="${esc(d.id)}" data-operation="${op}" ${maintenanceDisabled ? "disabled" : ""}>${label}</button>`).join("")}</div></details></article>`;
}
function hardwareDiscoveryPanel(r) {
  return `<section class="panel hardware-panel"><div class="panel-header"><h2>Erkannte Bandlaufwerke</h2><span class="subtle-caption">${r.discovery.time ? esc(ago(r.discovery.time)) : "Worker-Erkennung steht aus"}</span></div><div class="hardware-drive-list">${r.discovery.drives.length ? r.discovery.drives.map(d => hardwareDriveCard(d, r)).join("") : '<p class="hint">Kein Bandlaufwerk erkannt. Einschalten und Anschluss prüfen.</p>'}</div></section>`;
}
async function hardwarePage() {
  const r = await api("/hardware");
  return (
    heading(
      "Laufwerke & Bandpflege.",
      "Automatische Erkennung. Jede schreibende Aktion braucht eine eigene Freigabe.",
      `<button class="button" id="scan-drives">${icon("sync")}Status & Diagnose aktualisieren</button>`,
    ) +
    driveStatusPanel(r.status) +
    `<section class="panel"><div class="panel-header"><h2>Betriebsart</h2><span class="badge neutral">${r.mode === "physical" ? (state.node.capabilities.physical_tape ? "Physischer Archivbetrieb" : "Physische Bandwartung") : "Simulator"}</span></div><div class="panel-body"><form id="mode-form" class="form-grid"><label>Betriebsart<select name="mode"><option value="simulator" ${r.mode === "simulator" ? "selected" : ""}>Simulator</option><option value="physical" ${r.mode === "physical" ? "selected" : ""} ${r.physical_maintenance_enabled ? "" : "disabled"}>Physischer Bandbetrieb</option></select></label><div class="form-actions"><button class="button primary" type="submit">Betriebsart übernehmen</button></div></form>${note(r.message, "warning")}<p class="hint">Der Moduswechsel schreibt kein Band. Initialisierung, Volltest und Löschen benötigen jeweils eine eigene Bestätigung.</p></div></section>` +
    hardwareDiscoveryPanel(r) +
    diagnosticDetails(r.status) +
    `<section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Bandtests und Löschvorgänge</h2></div>${table(
      ["Vorgang", "Medium", "Phase", "Fortschritt", "Ergebnis"],
      r.maintenance.map(
        (m) =>
          `<tr><td>${esc(m.operation)}<small class="hint mono">${esc(short(m.approval_id))}</small></td><td class="mono">${esc(m.drive.medium_serial)}</td><td>${esc(labels[m.phase] || m.phase)}</td><td>${bytes(m.bytes)}${m.total_bytes ? " / " + bytes(m.total_bytes) : ""}<small class="hint">${m.bytes_per_second ? bytes(m.bytes_per_second) + "/s" : "Keine belastbare ETA"}</small></td><td>${badge(m.state)}${m.result?.sha256 ? `<small class="hint mono">SHA-256 ${esc(m.result.sha256)}</small>` : ""}${m.error ? `<small class="error-text">${esc(m.error)}</small>` : ""}${m.result?.state === "SAMPLE_VERIFIED" ? '<small class="hint">Testbereich vollständig verifiziert; keine Vollqualifikation des Mediums.</small>' : ""}${m.result?.state === "ERASE_COMMAND_COMPLETED" ? '<small class="hint">Löschkommando abgeschlossen; keine zertifizierte Datenträgerbereinigung.</small>' : ""}</td></tr>`,
      ),
      "Noch keine Bandwartung ausgeführt",
    )}</section>`
  );
}
async function logsPage() {
  const r = await api("/events?limit=200");
  return (
    heading(
      "Nichts bleibt im Ungefähren.",
      "Persistente Ereignisse und Fehler aus deinem Archivierungsablauf.",
    ) +
    `<section class="panel"><div class="panel-header"><h2>Ereignisprotokoll</h2><span class="subtle-caption">Die letzten 200 Ereignisse</span></div>${table(
      ["Zeit", "Level", "Ereignis", "Job", "Details"],
      r.items.map(
        (e) =>
          `<tr><td>${esc(date(e.time))}</td><td>${badge(e.level === "ERROR" ? "FAILED" : e.level)}</td><td><strong>${esc(eventLabel(e))}</strong></td><td><button class="button subtle" data-job="${esc(e.job_id)}">${esc(short(e.job_id))}</button></td><td><span class="truncate mono" title="${esc(JSON.stringify(e.details))}">${esc(JSON.stringify(e.details))}</span></td></tr>`,
      ),
      "Noch keine Protokolle",
    )}</section>`
  );
}
function accountSettings(users) {
  const account = state.account;
  const roleName = { admin: "Administrator", operator: "Operator", viewer: "Nur lesen" };
  return `<div class="settings-account-grid">
    <section class="panel"><div class="panel-header"><div><h2>Sprache</h2><p>Oberfläche und Datumsformat</p></div></div><div class="panel-body">
      <label class="settings-field">Sprache<select id="language-select" aria-label="Sprache"><option value="de" ${getLanguage() === "de" ? "selected" : ""}>Deutsch</option><option value="en" ${getLanguage() === "en" ? "selected" : ""}>Englisch</option></select></label>
      <small class="hint">Die Auswahl wird für dieses Benutzerkonto gespeichert.</small></div></section>
    <section class="panel"><div class="panel-header"><div><h2>Mein Konto</h2><p>${esc(account?.username || "")}</p></div><span class="badge blue">${roleName[account?.role] || ""}</span></div><div class="panel-body">
      <form id="own-password-form"><div class="form-grid"><label>Aktuelles Passwort<input name="current_password" type="password" autocomplete="current-password" required></label><label>Neues Passwort<input name="new_password" type="password" autocomplete="new-password" minlength="12" required><small class="hint">Mindestens 12 Zeichen</small></label></div><div class="form-actions"><button class="button" type="submit">Passwort ändern</button></div></form>
      <div class="security-future"><strong>Zwei-Faktor-Authentifizierung</strong><small>Für eine spätere Version vorbereitet; derzeit nicht aktivierbar.</small></div>
    </div></section></div>
    ${account?.role === "admin" ? `<section class="panel user-management"><div class="panel-header"><div><h2>Benutzerverwaltung</h2><p>Lokale Konten dieses Node; Zugangsdaten werden nicht mit dem Katalog synchronisiert.</p></div><button class="button primary" id="new-user">${icon("plus")}Benutzer hinzufügen</button></div>${table(["Benutzer", "Berechtigung", "Status", ""], users.map((u) => `<tr><td><strong>${esc(u.username)}</strong><small class="cell-sub">${esc(date(u.created))}</small></td><td>${esc(roleName[u.role])}</td><td>${badge(u.enabled ? "ACTIVE" : "DISABLED")}</td><td><div class="button-row"><button class="button small" data-edit-user="${esc(u.id)}">Bearbeiten</button><button class="button small" data-password-user="${esc(u.id)}">Passwort setzen</button></div></td></tr>`), "Noch keine Benutzer")}</section>` : ""}`;
}
async function settingsPage() {
  const n = state.node;
  const storage =
    n.role === "archive" ? (await api("/storage-resources")).items : [];
  const users = state.account?.role === "admin" ? (await api("/users")).items : [];
  const power = n.shutdown_enabled && state.account?.role === "admin"
    ? await api("/system/poweroff") : null;
  return (
    heading(
      "Unter deiner Kontrolle.",
      "Node-Rolle, Module und bewusst konfigurierte Ressourcen.",
      n.role === "archive" && state.account?.role === "admin"
        ? `<button class="button" id="new-source">Quelle hinzufügen</button><button class="button primary" id="new-staging">Staging hinzufügen</button>`
        : "",
    ) +
    accountSettings(users) +
    `${power ? `<section class="panel" style="margin-bottom:22px"><div class="panel-header"><div><h2>Server herunterfahren</h2><p>Nur Administratoren. Laufende Archiv-, Staging-, Prüf- oder Bandvorgänge sperren den Shutdown.</p></div><button class="button" id="request-poweroff" ${!power.service_active || power.pending ? "disabled" : ""}>Herunterfahren …</button></div>${!power.service_active ? `<div class="panel-body">${note("Der geschützte Shutdown-Dienst ist nicht aktiv.", "warning")}</div>` : power.pending ? `<div class="panel-body">${note("Herunterfahren wird vorbereitet.", "info")}</div>` : power.last?.state === "FAILED" ? `<div class="panel-body">${note(`${translate("Letzter Shutdown-Versuch fehlgeschlagen:")} ${power.last.error || translate("Unbekannter Fehler")}`, "warning")}</div>` : ""}</section>` : ""}` +
    `${n.role === "archive" ? `<section class="panel" style="margin-bottom:22px"><div class="panel-header"><h2>Quellen & Staging</h2></div>${resourceTable(storage)}</section>` : ""}<div class="split"><section class="panel"><div class="panel-header"><h2>Node-Konfiguration</h2><span class="badge neutral">v${esc(n.version)}</span></div><div class="panel-body"><dl class="detail-list"><dt>Name</dt><dd>${esc(n.name)}</dd><dt>Rolle</dt><dd>${n.role === "archive" ? "Archive Node" : "Catalog Node"}</dd><dt>Node-ID</dt><dd class="mono">${esc(n.id)}</dd><dt>Authentifizierung</dt><dd>Passwortgeschützte Sitzung · CSRF-Schutz</dd><dt>Reguläre LTO-Archivierung</dt><dd>${n.capabilities.physical_tape ? "Administrativ freigegeben" : "Administrativ gesperrt"}</dd><dt>Verbindungen</dt><dd>Keine Telemetrie oder CDN-Abhängigkeit</dd></dl><p class="hint" style="margin-top:22px">Optionale Katalogdienste und Snapshot-Ziele verwaltest du unter Synchronisation. Änderungen gelten ohne Neustart. Quellen und Staging verwaltest du hier. Administrativ freigegebene Verzeichnisbereiche, Dienstrechte und Bind-Adresse bleiben in der geschützten Konfiguration.</p></div></section><section class="panel"><div class="panel-header"><h2>Aktive Module</h2></div><div class="panel-body">${n.modules.map((m) => `<div class="node-detail"><div class="node-detail-icon">${icon(m.id === "archive" ? "tape" : m.id === "catalog" ? "search" : "sync")}</div><div><strong>${esc(m.label)}</strong><small>${m.writable ? "Steuerung auf diesem Node" : "Lesender Zugriff"}</small></div><span class="status-dot"></span></div>`).join("")}</div></section><section class="panel"><div class="panel-header"><h2>Freigegebene Quellen</h2></div><div class="panel-body">${n.sources.length ? n.sources.map((s) => `<div class="node-detail"><div class="node-detail-icon">${icon("folder")}</div><div><strong>${esc(s.label)}</strong><small>${esc(s.id)}</small></div></div>`).join("") : empty("Keine lokalen Datenquellen", n.role === "catalog" ? "Der Catalog Node benötigt keine Quelldateisysteme." : "Quellen in der Node-Konfiguration freigeben.", "folder", "", true)}</div></section><section class="panel"><div class="panel-header"><h2>Offen und wiederherstellbar</h2></div><div class="panel-body">${note("PAX-TAR, SHA-256 und selbstbeschreibende Manifeste. Der Katalog lässt sich aus Medieninhalt rekonstruieren.")}<p class="hint" style="margin-top:15px">System-Snapshots, Hardwareverschlüsselung und automatische Medienrotation sind noch nicht freigegeben. Unvollständige Archive bleiben eindeutig gekennzeichnet.</p></div></section></div>`
  );
}
const renderers = {
  dashboard,
  planning,
  staging: stagingPage,
  jobs: jobsPage,
  catalog: catalogPage,
  archives: archivesPage,
  media: mediaPage,
  restore: restorePage,
  integrity: integrityPage,
  sync: syncPage,
  hardware: hardwarePage,
  logs: logsPage,
  settings: settingsPage,
};

export { renderers, driveStatusPanel, hardwareDiscoveryPanel, diagnosticDetails };
