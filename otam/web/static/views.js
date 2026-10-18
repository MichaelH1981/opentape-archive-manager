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
import {
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
} from "./ui.js";
import { api } from "./api.js";
async function dashboard() {
  const [staging, events] = await Promise.all([
    api("/staging"),
    api("/events?limit=60"),
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
    ],
    [
      "file",
      "Dateien im Katalog",
      num(o.file_count),
      "Jede Archivkopie einzeln erfasst",
    ],
    [
      "tape",
      "Inventarisierte Medien",
      num(o.media_count),
      "Mit eindeutiger Medien-ID",
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
    ],
  ];
  const activeHtml = active
    ? `<div class="panel-body"><div class="archive-current"><div class="file-tile">${icon("archive")}</div><div><strong>Archiv ${esc(short(active.archive_id))}</strong><small>Job ${esc(short(active.job_id))} · ${esc(labels[active.phase] || active.phase)}</small></div>${badge(active.state)}</div><div class="progress-meta"><span>${bytes(active.progress_bytes)} / ${bytes(active.total_bytes)}</span><strong>${Math.min(100, Math.round((active.progress_bytes / Math.max(1, active.total_bytes)) * 100))}%</strong></div>${progress((active.progress_bytes / Math.max(1, active.total_bytes)) * 100)}${pipeline(active.phase)}<div class="throughput"><div class="throughput-number"><small>Letzter Simulatortransfer</small><strong>${latest ? bytes(latest.details.bytes_per_second) : "—"}</strong><span>${latest ? "/s" : ""}</span></div>${sparkline(transfer)}</div></div>`
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
    `<div class="stats">${stats.map(([ic, title, value, foot]) => `<section class="stat"><div class="stat-top"><span class="stat-title">${esc(title)}</span><span class="stat-icon">${icon(ic)}</span></div><div class="stat-value">${esc(value)}</div><div class="stat-foot ${ic === "shield" ? "positive" : ""}">${ic === "shield" ? icon("check") : ""}${esc(foot)}</div></section>`).join("")}</div><div class="dashboard-grid"><div class="main-column"><section class="panel"><div class="panel-header"><div><h2>Archivierungsablauf</h2><p>Vom lokalen Staging bis zur geprüften Kopie</p></div>${active ? `<button class="button subtle" data-job="${esc(active.job_id)}">Job ansehen ${icon("arrow")}</button>` : badge("READY")}</div>${activeHtml}</section><section class="panel"><div class="panel-header"><h2>Zuletzt archiviert</h2><a class="button subtle" href="#archives">Alle Archive ${icon("arrow")}</a></div>${table(["Archiv", "Medium", "Größe", "Status"], recentRows, "Dein erstes Archiv wartet")}<div class="panel-bottom"><span>${num(o.archive_count)} Archive im Katalog</span><span>SHA-256 · Offenes TAR-Format</span></div></section><section class="panel"><div class="panel-header"><h2>Letzte Aktivitäten</h2><a class="button subtle" href="#logs">Alle Protokolle ${icon("arrow")}</a></div>${activities ? `<div class="activity-list">${activities}</div>` : empty("Noch keine Aktivitäten", "Abgeschlossene und fehlgeschlagene Schritte werden dauerhaft protokolliert.", "activity", "", true)}</section></div><aside class="side-column">${storageCard(staging.storage)}<section class="panel info-card"><h2>Dein Archivsystem</h2><div class="node-detail"><div class="node-detail-icon">${icon("server")}</div><div><strong>${esc(n.name)}</strong><small>${replica ? "Eigenständiger Katalogdienst" : "Archive Node · Simulatorbetrieb"}</small></div><span class="status-dot"></span></div>${!replica ? `<div class="node-detail"><div class="node-detail-icon">${icon("activity")}</div><div><strong>Auftragsworker</strong><small>${Date.now() / 1000 - n.worker_heartbeat < 20 ? "Verbunden · " + esc(ago(n.worker_heartbeat)) : "Kein aktuelles Lebenszeichen"}</small></div><span class="status-dot ${Date.now() / 1000 - n.worker_heartbeat < 20 ? "" : "off"}"></span></div>` : ""}<div class="node-detail"><div class="node-detail-icon">${icon("sync")}</div><div><strong>${replica ? "Letzter empfangener Stand" : "Katalog-Synchronisation"}</strong><small>${replica ? (n.snapshot ? esc(ago(n.snapshot.created)) : "Noch nicht empfangen") : n.last_push ? esc(ago(n.last_push.time)) : "Noch nicht synchronisiert"}</small></div></div><div class="node-detail"><div class="node-detail-icon">${icon("shield")}</div><div><strong>Verifikation vor Erfolg</strong><small>Vollständiges Rücklesen · SHA-256</small></div></div></section>${note(replica ? "Dieser Katalog zeigt den letzten empfangenen Stand. Änderungen am ausgeschalteten Bandserver sind hier noch nicht enthalten." : "Simulatorbetrieb: Der Archivierungsablauf ist nutzbar. Reale LTO-Schreibzugriffe warten auf die Testband-Abnahme.", "info")}</aside></div>`
  );
}
async function planning() {
  const jobs = (await api("/jobs")).items.filter((j) => j.kind === "archive");
  return (
    heading(
      "Gut geplant. Sicher archiviert.",
      "Wähle Quelle und Staging für den vollständigen Archivplan.",
      `<button class="button" id="new-source">${icon("folder")}Quelle hinzufügen</button>`,
    ) +
    `${state.node.operation_mode === "physical" ? note("Für Simulator-Archivierungen zuerst unter Hardware in den Simulatorbetrieb wechseln. Physische Archivierung wartet auf Bandformat-Abnahme.", "warning") : ""}<div class="split"><section class="panel"><div class="panel-header"><div><h2>Neue Archivierung planen</h2><p>Quelldaten bleiben vollständig erhalten.</p></div><span class="badge neutral">01 / PLANUNG</span></div><div class="panel-body"><form id="plan-form"><div class="form-grid"><label class="full">Datenquelle<select name="source_id" required><option value="">Quelle auswählen</option>${state.node.sources.map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("")}</select><small class="hint">Nur serverseitig freigegebene Verzeichnisse stehen zur Auswahl.</small></label><label>Staging-Verzeichnis<select name="staging_id" required>${(state.node.staging_locations || []).map((r) => `<option value="${esc(r.id)}">${esc(r.label)} · ${esc(r.path)}</option>`).join("")}</select></label><label>Zielmedium<select name="media_id" required><option value="">Medium auswählen</option>${mediaOptions()}</select></label><label>TAR-Zielgröße in GB<input name="target" type="number" min="0.001" max="10000" step="0.001" value="75" required><small class="hint">Große Einzeldateien bleiben zusammen.</small></label></div><div class="form-actions"><button class="button primary" type="submit">${icon("calendar")}Inventarisieren & planen</button></div></form></div></section><div class="stack"><section class="panel"><div class="panel-header"><h2>Ein Plan, acht sichere Schritte.</h2></div><div class="panel-body">${pipeline("INVENTORY")}<p class="subtle-caption" style="margin-top:22px">OTAM liest Dateiinformationen, berechnet SHA-256 und plant vollständige Archive. Vor dem Schreiben bestätigst du Umfang, Medium und den unveränderten Plan.</p></div></section>${!state.media.length ? note("Für den ersten vollständigen Testzyklus ein Simulatormedium im Bandinventar erstellen.", "info") : ""}${!state.node.sources.length ? note("Noch keine Quelle freigegeben. Über „Quelle hinzufügen“ ein Serververzeichnis auswählen.", "warning") : ""}</div></div><section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Deine Archivpläne</h2><span class="subtle-caption">${jobs.length} Jobs</span></div>${table(
      ["Plan", "Medium", "Erstellt", "Status", ""],
      jobs.map(
        (j) =>
          `<tr><td><strong>Archivierung ${esc(short(j.id))}</strong></td><td>${esc(j.label || "—")}</td><td>${esc(date(j.created))}</td><td>${badge(j.state)}</td><td><button class="button small" data-job="${esc(j.id)}">Plan prüfen</button></td></tr>`,
      ),
      "Noch kein Archivplan",
    )}</section>`
  );
}
async function stagingPage() {
  const result = await api("/staging");
  const rows = result.items;
  return (
    heading(
      "Vorbereitet für den langen Weg.",
      "Vollständige lokale TARs. Erst geprüft, dann zum Band.",
      `<button class="button primary" id="new-staging">${icon("layers")}Staging hinzufügen</button>`,
    ) +
    `<section class="panel" style="margin-bottom:22px"><div class="panel-header"><h2>Staging-Verzeichnisse</h2></div>${resourceTable((result.locations || []).filter((r) => r.kind === "staging"))}</section><div class="dashboard-grid"><div class="main-column">${rows.length ? rows.map((s) => `<section class="panel job-card"><div class="job-top"><div><strong>Archiv ${esc(short(s.archive_id))}</strong><small>Job ${esc(short(s.job_id))} · ${esc(ago(s.updated))}</small></div>${badge(s.state)}</div><div class="progress-meta"><span>${esc(labels[s.phase] || s.phase)}</span><strong>${bytes(s.progress_bytes)} / ${bytes(s.total_bytes)}</strong></div>${progress((s.progress_bytes / Math.max(1, s.total_bytes)) * 100)}${pipeline(s.phase)}${s.error ? `<p class="error-text">${esc(s.error)}</p>` : ""}<div class="button-row"><button class="button small" data-job="${esc(s.job_id)}">Job und Plan ansehen ${icon("arrow")}</button></div></section>`).join("") : `<section class="panel">${empty("Noch keine Archive im Staging", "Erstelle einen Plan und starte die lokale Vorbereitung.", "layers", state.node.role === "archive" ? linkButton("Planung öffnen", "planning", "calendar", true) : "")}</section>`}</div><aside class="side-column">${storageCard(result.storage)}${note("Staging-Archive bleiben bis zur erfolgreichen Rückleseverifikation erhalten. Nur von OTAM verwaltete temporäre Dateien werden danach bereinigt.")}</aside></div>`
  );
}
async function jobsPage() {
  const jobs = (await api("/jobs")).items;
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
          `<tr><td><strong>${esc(kindLabel(j.kind))}</strong><div class="cell-sub mono">${esc(short(j.id))}</div></td><td>${esc(j.label || "—")}</td><td>${esc(labels[j.phase] || j.phase || "—")}</td><td>${badge(j.state)}</td><td>${esc(ago(j.updated))}</td><td><button class="button small" data-job="${esc(j.id)}">Details ${icon("arrow")}</button></td></tr>`,
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
        ? `<button class="button primary" id="new-medium">${icon("plus")}Testmedium erstellen</button>`
        : "",
    ) +
    (!state.media.length
      ? `<section class="panel">${empty("Noch kein Medium inventarisiert", "Erstelle ein ausdrücklich als Simulation gekennzeichnetes Testmedium für deinen ersten Archivierungszyklus.", "tape")}</section>`
      : `<div class="cards-grid">${state.media.map((m) => `<section class="panel media-card"><div class="media-top"><div class="media-illustration">${icon("tape")}</div>${badge(m.state)}</div><h2>${esc(m.label)}</h2><span class="mono">${esc(m.id)}</span><dl><div><dt>Medienklasse</dt><dd>${m.class === "permanent" ? "Dauerarchiv" : "Rotierende Sicherung"}</dd></div><div><dt>Generation</dt><dd>LTO-${num(m.generation)} · ${bytes(m.capacity)}</dd></div><div><dt>Archive</dt><dd>${num(m.archive_count)}</dd></div><div><dt>Letzte Prüfung</dt><dd>${esc(m.last_verified ? ago(m.last_verified) : "Noch nicht")}</dd></div><div><dt>Lagerort</dt><dd>${esc(m.location || "Nicht hinterlegt")}</dd></div><div><dt>Backend</dt><dd>${state.node.role === "catalog" ? "Replizierter Katalog" : m.mounted ? "Simulator eingebunden" : "Nicht eingebunden"}</dd></div></dl><div class="progress-meta"><span>${bytes(m.used)} verwendet</span><strong>${Math.round((m.used / m.capacity) * 100)}%</strong></div>${progress((m.used / m.capacity) * 100)}<div class="button-row"><button class="button small" data-media-files="${esc(m.id)}">${icon("search")}Dateien</button>${state.node.role === "archive" && m.mounted ? `<button class="button small" data-verify="${esc(m.id)}">${icon("shield")}Prüfen</button><button class="icon-button" data-medium-tools="${esc(m.id)}" aria-label="Werkzeuge für ${esc(m.label)}">⋯</button>` : ""}</div></section>`).join("")}</div>`)
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
function resourceTable(items) {
  return table(
    ["Verzeichnis", "Pfad", "Speicher", "Verwaltung"],
    items.map(
      (r) =>
        `<tr><td><strong>${esc(r.label)}</strong><small class="hint">${r.kind === "source" ? "Quelle" : "Staging"}</small></td><td class="mono">${esc(r.path)}</td><td>${r.available ? `${bytes(r.storage?.free)} frei · ${esc(r.storage?.type || "")}` : "Nicht erreichbar"}</td><td><button class="button subtle" data-remove-resource="${esc(r.id)}">Abmelden</button></td></tr>`,
    ),
    "Noch keine Verzeichnisse registriert",
  );
}
async function hardwarePage() {
  const r = await api("/hardware");
  return (
    heading(
      "Laufwerke & Bandpflege.",
      "Automatische Erkennung. Jede schreibende Aktion braucht eine eigene Freigabe.",
      `<button class="button" id="scan-drives">${icon("sync")}Neu erkennen</button>`,
    ) +
    `<section class="panel"><div class="panel-header"><h2>Betriebsart</h2><span class="badge neutral">${r.mode === "physical" ? "Physische Bandwartung" : "Simulator"}</span></div><div class="panel-body"><form id="mode-form" class="form-grid"><label>Betriebsart<select name="mode"><option value="simulator" ${r.mode === "simulator" ? "selected" : ""}>Simulator</option><option value="physical" ${r.mode === "physical" ? "selected" : ""} ${r.physical_maintenance_enabled ? "" : "disabled"}>Physischer Wartungsbetrieb</option></select></label><div class="form-actions"><button class="button primary" type="submit">Betriebsart übernehmen</button></div></form>${note(r.message, "warning")}<p class="hint">Der Moduswechsel schreibt kein Band. Volltest und Löschen müssen separat bestätigt werden. Reguläre Archivierung auf physische Bänder wird erst nach Bandformat-Abnahme freigegeben.</p></div></section>` +
    `<section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Erkannte Bandlaufwerke</h2><span class="subtle-caption">${r.discovery.time ? esc(ago(r.discovery.time)) : "Worker-Erkennung steht aus"}</span></div>${table(
      ["Laufwerk", "Gerät", "Eingelegtes Medium", "Aktionen"],
      r.discovery.drives.map(
        (d) =>
          `<tr><td><strong>${esc(d.vendor || "")} ${esc(d.model || "")}</strong><small class="hint mono">Seriennummer ${esc(d.serial || "unbekannt")}</small></td><td class="mono">${esc(d.device)}</td><td><span class="mono">${esc(d.medium_serial || "Nicht identifiziert")}</span><small class="hint">${esc(d.error || "Bereit")}</small></td><td>${[
            ["qualify", "Vollständig testen"],
            ["erase-short", "Kurz löschen"],
            ["erase-long", "Lang löschen"],
          ]
            .map(
              ([op, label]) =>
                `<button class="button subtle" data-maintenance-drive="${esc(d.id)}" data-operation="${op}" ${r.mode !== "physical" || !d.ready || Date.now() / 1000 - r.discovery.time > 30 ? "disabled" : ""}>${label}</button>`,
            )
            .join("")}</td></tr>`,
      ),
      "Kein Bandlaufwerk erkannt. Einschalten und Anschluss prüfen; die Erkennung wird automatisch aktualisiert.",
    )}</section>` +
    `<section class="panel" style="margin-top:22px"><div class="panel-header"><h2>Bandtests und Löschvorgänge</h2></div>${table(
      ["Vorgang", "Medium", "Phase", "Fortschritt", "Ergebnis"],
      r.maintenance.map(
        (m) =>
          `<tr><td>${esc(m.operation)}<small class="hint mono">${esc(short(m.approval_id))}</small></td><td class="mono">${esc(m.drive.medium_serial)}</td><td>${esc(labels[m.phase] || m.phase)}</td><td>${bytes(m.bytes)}${m.total_bytes ? " / " + bytes(m.total_bytes) : ""}<small class="hint">${m.bytes_per_second ? bytes(m.bytes_per_second) + "/s" : "Keine belastbare ETA"}</small></td><td>${badge(m.state)}${m.result?.sha256 ? `<small class="hint mono">SHA-256 ${esc(m.result.sha256)}</small>` : ""}${m.error ? `<small class="error-text">${esc(m.error)}</small>` : ""}${m.result?.state === "ERASE_COMMAND_COMPLETED" ? '<small class="hint">Löschkommando abgeschlossen; keine zertifizierte Datenträgerbereinigung.</small>' : ""}</td></tr>`,
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
async function settingsPage() {
  const n = state.node;
  const storage =
    n.role === "archive" ? (await api("/storage-resources")).items : [];
  return (
    heading(
      "Unter deiner Kontrolle.",
      "Node-Rolle, Module und bewusst konfigurierte Ressourcen.",
      n.role === "archive"
        ? `<button class="button" id="new-source">Quelle hinzufügen</button><button class="button primary" id="new-staging">Staging hinzufügen</button>`
        : "",
    ) +
    `${n.role === "archive" ? `<section class="panel" style="margin-bottom:22px"><div class="panel-header"><h2>Quellen & Staging</h2></div>${resourceTable(storage)}</section>` : ""}<div class="split"><section class="panel"><div class="panel-header"><h2>Node-Konfiguration</h2><span class="badge neutral">v${esc(n.version)}</span></div><div class="panel-body"><dl class="detail-list"><dt>Name</dt><dd>${esc(n.name)}</dd><dt>Rolle</dt><dd>${n.role === "archive" ? "Archive Node" : "Catalog Node"}</dd><dt>Node-ID</dt><dd class="mono">${esc(n.id)}</dd><dt>Authentifizierung</dt><dd>Passwortgeschützte Sitzung · CSRF-Schutz</dd><dt>Reguläre LTO-Archivierung</dt><dd>Bis zur Bandformat-Abnahme gesperrt</dd><dt>Verbindungen</dt><dd>Keine Telemetrie oder CDN-Abhängigkeit</dd></dl><p class="hint" style="margin-top:22px">Optionale Katalogdienste und Snapshot-Ziele verwaltest du unter Synchronisation. Änderungen gelten ohne Neustart. Quellen und Staging verwaltest du hier. Administrativ freigegebene Verzeichnisbereiche, Dienstrechte und Bind-Adresse bleiben in der geschützten Konfiguration.</p></div></section><section class="panel"><div class="panel-header"><h2>Aktive Module</h2></div><div class="panel-body">${n.modules.map((m) => `<div class="node-detail"><div class="node-detail-icon">${icon(m.id === "archive" ? "tape" : m.id === "catalog" ? "search" : "sync")}</div><div><strong>${esc(m.label)}</strong><small>${m.writable ? "Steuerung auf diesem Node" : "Lesender Zugriff"}</small></div><span class="status-dot"></span></div>`).join("")}</div></section><section class="panel"><div class="panel-header"><h2>Freigegebene Quellen</h2></div><div class="panel-body">${n.sources.length ? n.sources.map((s) => `<div class="node-detail"><div class="node-detail-icon">${icon("folder")}</div><div><strong>${esc(s.label)}</strong><small>${esc(s.id)}</small></div></div>`).join("") : empty("Keine lokalen Datenquellen", n.role === "catalog" ? "Der Catalog Node benötigt keine Quelldateisysteme." : "Quellen in der Node-Konfiguration freigeben.", "folder", "", true)}</div></section><section class="panel"><div class="panel-header"><h2>Offen und wiederherstellbar</h2></div><div class="panel-body">${note("PAX-TAR, SHA-256 und selbstbeschreibende Manifeste. Der Katalog lässt sich aus Medieninhalt rekonstruieren.")}<p class="hint" style="margin-top:15px">System-Snapshots, Hardwareverschlüsselung und automatische Medienrotation sind noch nicht freigegeben. Unvollständige Archive bleiben eindeutig gekennzeichnet.</p></div></section></div>`
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

export { renderers };
