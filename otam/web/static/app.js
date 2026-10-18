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
import { getLanguage, localize, setLanguage, translate } from "./i18n.js";
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
import { api, enqueue, refreshBase } from "./api.js";
import { renderers } from "./views.js";
let renderId = 0;
function applyPermissions(root) {
  const role = state.account?.role || "viewer";
  if (role !== "admin")
    $$("#new-source, #new-staging, #new-target, #mode-form, [data-maintenance-drive], [data-remove-resource], [data-edit-target], [data-delete-target], [data-init-target]", root)
      .forEach((element) => (element.hidden = true));
  if (role === "viewer")
    $$("#plan-form, #new-medium, #sync-now, #verify-form, [data-verify], [data-stage], [data-backup], [data-resume], [data-revalidate], [data-recover], [data-rebuild], [data-restore-group]", root)
      .forEach((element) => (element.hidden = true));
}
async function render() {
  const id = ++renderId;
  let page = location.hash.slice(1) || "dashboard";
  if (!renderers[page]) page = "dashboard";
  if (state.node?.role === "catalog" && ["planning", "hardware"].includes(page))
    page = "catalog";
  state.page = page;
  $("#breadcrumb-title").textContent = titles[page];
  document.title = translate(titles[page]) + " · OTAM";
  $$("nav a[data-page]").forEach((a) =>
    a.classList.toggle("active", a.dataset.page === page),
  );
  try {
    const html = await renderers[page]();
    if (id !== renderId) return;
    const freshness =
      state.node.role === "catalog"
        ? `<div class="catalog-freshness">${note(state.node.snapshot ? `Katalogstand: ${date(state.node.snapshot.created)} · Eigenständige Kopie. Neue Änderungen erscheinen erst nach der nächsten Synchronisation.` : "Noch kein Katalog empfangen. Der Herausgeber muss zuerst einen gültigen Stand veröffentlichen.", "info")}</div>`
        : "";
    $("#content").innerHTML = freshness + html;
    paintIcons($("#content"));
    localize(document);
    applyPermissions($("#content"));
    bindForms();
  } catch (e) {
    if (id !== renderId) return;
    $("#content").innerHTML =
      heading("Diese Ansicht ist gerade nicht verfügbar.", e.message) +
      `<button class="button" id="retry">Erneut versuchen</button>`;
    localize($("#content"));
  }
}
async function showJob(id) {
  const j = await api("/jobs/" + encodeURIComponent(id)),
    p = j.plan;
  let html = `<dl class="detail-list"><dt>Job-ID</dt><dd class="mono">${esc(j.id)}</dd><dt>Status</dt><dd>${badge(j.state)}</dd><dt>Phase</dt><dd>${esc(labels[j.phase] || j.phase || "—")}</dd><dt>Erstellt</dt><dd>${esc(date(j.created))}</dd></dl>`;
  if (p?.archives) {
    html += `<h3>Geprüfter Archivplan</h3><dl class="detail-list"><dt>Quelle</dt><dd>${esc(p.source)}</dd><dt>Staging</dt><dd>${esc(j.storage_binding?.staging_path || "Bisheriges Standard-Staging")}</dd><dt>Medium</dt><dd>${esc(mediaName(p.media_id))}</dd><dt>Dateien</dt><dd>${num(p.file_count)}</dd><dt>Nutzdaten</dt><dd>${bytes(p.payload_bytes)}</dd><dt>Bedarf mit Reserve</dt><dd>${bytes(p.required_estimate)}</dd><dt>Verfügbar</dt><dd>${bytes(p.available)}</dd><dt>Plan-SHA-256</dt><dd class="mono">${esc(p.sha256)}</dd></dl><h3>Vorgesehene TAR-Archive</h3>${table(
      ["Archiv", "Dateien", "Nutzdaten"],
      p.archives.map(
        (a) =>
          `<tr><td class="mono">${esc(short(a.archive_id))}</td><td>${num(a.file_count)}</td><td>${bytes(a.payload_bytes)}</td></tr>`,
      ),
    )}`;
  }
  if (j.staging?.length)
    html += `<h3>Vorbereitung und Transfer</h3>${j.staging.map((s) => `<div class="progress-meta"><span>${esc(short(s.archive_id))} · ${esc(labels[s.phase] || s.phase)}</span>${badge(s.state)}</div>${progress((s.progress_bytes / Math.max(1, s.total_bytes)) * 100)}`).join("")}`;
  if (j.error) html += `<p class="error-text">${esc(j.error)}</p>`;
  if (j.report)
    html += `<h3>Abschlussbericht</h3><pre class="code-block">${esc(JSON.stringify(j.report, null, 2))}</pre>`;
  if (
    state.node.role === "archive" &&
    p?.archives &&
    ["PLANNED", "STAGED", "FAILED", "INTERRUPTED"].includes(j.state)
  ) {
    html += `<div class="button-row">${["PLANNED", "STAGED"].includes(j.state) ? `<button class="button" data-stage="${esc(j.id)}">${icon("layers")}Lokal vorbereiten</button><button class="button primary" data-backup="${esc(j.id)}">${icon("tape")}Archivierung bestätigen</button>` : `<button class="button" ${j.tape_attempted ? "data-resume" : "data-revalidate"}="${esc(j.id)}">${icon("restore")}${j.tape_attempted ? "Wiederaufnahme prüfen" : "Staging erneut prüfen"}</button>`}</div>`;
  }
  modal(kindLabel(j.kind) + " · " + short(j.id), html);
}
async function confirmBackup(id, resume = false) {
  const j = await api("/jobs/" + encodeURIComponent(id));
  if (!j.plan?.archives) throw Error("Archivplan fehlt");
  modal(
    resume ? "Archivierung bewusst wiederaufnehmen" : "Archivierung bestätigen",
    `<p>Der bestätigte Auftrag schreibt ausschließlich vollständige, geprüfte lokale TAR-Archive auf das zugeordnete <strong>Simulatormedium ${esc(mediaName(j.plan.media_id))}</strong> und liest sie vollständig zurück.</p>${resume ? note("Vor Wiederaufnahme wird die tatsächliche Mediensequenz erneut geprüft. Ein unvollständiges Medienende bleibt gesperrt.", "warning") : ""}<dl class="detail-list"><dt>Dateien</dt><dd>${num(j.plan.file_count)}</dd><dt>Nutzdaten</dt><dd>${bytes(j.plan.payload_bytes)}</dd><dt>Job-ID</dt><dd class="mono">${esc(id)}</dd></dl><form id="backup-form" data-job="${esc(id)}" data-hash="${esc(j.plan.sha256)}" data-resume="${resume}"><label style="margin-top:22px">Job-ID zur Bestätigung<input name="confirmation" autocomplete="off" required placeholder="Obige Job-ID eintragen"></label><label class="check-label" style="margin-top:17px"><input type="checkbox" name="reviewed" required>Ich habe Quelle, Umfang und Zielmedium geprüft.</label><label class="check-label" style="margin-top:14px"><input type="checkbox" name="prepare_all">Alle TARs vor dem ersten Schreibvorgang vorbereiten</label><div class="form-actions"><button class="button primary" type="submit">${icon("shield")}Bestätigten Job ausführen</button></div></form>`,
  );
  bindForms($("#modal"));
}
function newMedium() {
  modal(
    "Simulatormedium erstellen",
    `<p>Ein neues, unabhängiges Testmedium auf dem lokalen Dateisystem. Diese Aktion öffnet oder verändert kein physisches Bandlaufwerk.</p><form id="medium-form"><div class="form-grid"><label class="full">Bezeichnung<input name="label" placeholder="z. B. TEST-001" required maxlength="100"></label><label>Native Kapazität (GB)<input name="capacity" type="number" min="0.001" step="0.001" max="100000" value="800" required></label><label>Medienklasse<select name="media_class"><option value="permanent">Dauerarchiv</option><option value="rotation">Rotierende Sicherung</option></select></label></div><div class="form-actions"><button class="button primary" type="submit">Testmedium erstellen</button></div></form>`,
  );
  bindForms($("#modal"));
}
async function restoreGroup(key) {
  const files = [...state.selection.values()].filter(
    (f) => f.media_id + ":" + f.archive_id === key,
  );
  if (!files.length) return;
  const payload = {
    media_id: files[0].media_id,
    archive_id: files[0].archive_id,
    paths: files.map((f) => f.path),
    target_name:
      "restore-" +
      new Date()
        .toISOString()
        .replace(/[^0-9]/g, "")
        .slice(0, 14),
  };
  const r = await api("/restore-plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  modal(
    "Wiederherstellungsplan prüfen",
    `<dl class="detail-list"><dt>Medium</dt><dd>${esc(mediaName(r.media_id))}</dd><dt>Benötigte Medien</dt><dd>${r.media_count}</dd><dt>Banddateien</dt><dd>${r.tape_files.join(", ")}</dd><dt>Dateien</dt><dd>${num(r.files.length)}</dd><dt>Datenmenge</dt><dd>${bytes(r.payload_bytes)}</dd><dt>Ziel</dt><dd>${esc(r.target)}</dd></dl><form id="restore-form"><label style="margin-top:23px">Name des neuen Zielverzeichnisses<input name="target_name" value="${esc(payload.target_name)}" required pattern="[A-Za-z0-9][A-Za-z0-9._\-]{0,79}"></label><small class="hint">Ein vorhandenes Ziel wird nicht überschrieben. SHA-256 wird nach Restore geprüft.</small><div class="form-actions"><button class="button primary" type="submit">${icon("restore")}Wiederherstellung starten</button></div></form>`,
  );
  $("#restore-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const b = $("button[type=submit]", e.target);
    b.disabled = true;
    try {
      payload.target_name = new FormData(e.target).get("target_name");
      await enqueue("restore", payload);
      closeModal();
      location.hash = "jobs";
    } catch (err) {
      toast(err.message, true);
      b.disabled = false;
    }
  });
}
function downloadSelection() {
  const files = [...state.selection.values()];
  const blob = new Blob(
    [
      JSON.stringify(
        {
          format: "otam-restore-selection-v1",
          created: new Date().toISOString(),
          catalog_node: state.node.id,
          snapshot: state.node.snapshot?.sequence || null,
          files,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = "otam-restore-auswahl.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function resourceDialog(kind) {
  let current = "";
  modal(
    kind === "source" ? "Quelle hinzufügen" : "Staging hinzufügen",
    `<p>${kind === "source" ? "Vorhandenes Verzeichnis auf dem Server auswählen. Unterverzeichnisse lassen sich als eigene Quelle hinzufügen. Quelldaten bleiben erhalten." : "Vorhandenes lokales, schreibbares Verzeichnis auswählen. Netzwerk- und RAM-Dateisysteme sind für Staging gesperrt."}</p><form id="resource-form"><label>Bezeichnung<input name="label" required maxlength="100"></label><label style="margin-top:16px">Verzeichnispfad<input name="path" required readonly placeholder="Im Verzeichnisdialog auswählen"></label><div id="directory-list" style="margin-top:16px"></div><div class="form-actions"><button class="button primary" type="submit">Verzeichnis registrieren</button></div></form><p class="hint">Es werden nur administrativ freigegebene Bereiche angezeigt. Weitere Mounts und Dienstrechte werden am Server eingerichtet. Abmelden einer Ressource löscht keine Dateien.</p>`,
  );
  async function browsePath(path) {
    const listing = await api("/directories?path=" + encodeURIComponent(path));
    current = listing.path;
    $("[name=path]", $("#resource-form")).value = current;
    $("#directory-list").innerHTML =
      `<button type="button" class="button small" data-directory="${esc(listing.parent)}">${listing.path ? "Übergeordnetes Verzeichnis" : "Freigegebene Bereiche"}</button>${listing.items.map((item) => `<button type="button" class="button subtle directory-entry" data-directory="${esc(item.path)}">${icon("folder")}${esc(item.name)}</button>`).join("")}${listing.truncated ? '<p class="hint">Die ersten 500 Verzeichnisse werden angezeigt.</p>' : ""}`;
    $("#directory-list")
      .querySelectorAll("[data-directory]")
      .forEach((button) =>
        button.addEventListener("click", async () => {
          try {
            await browsePath(button.dataset.directory);
          } catch (error) {
            toast(error.message, true);
          }
        }),
      );
  }
  $("#resource-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    const button = $("button[type=submit]", e.target);
    button.disabled = true;
    try {
      await api("/storage-resources/" + newId(), {
        method: "PUT",
        body: JSON.stringify({ kind, label: d.get("label"), path: current }),
      });
      closeModal();
      await refreshBase();
      await render();
      toast("Verzeichnis registriert.");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  await browsePath("");
}
async function maintenanceDialog(drive, operation) {
  const approval = await api("/maintenance/prepare", {
    method: "POST",
    body: JSON.stringify({ drive_id: drive, operation }),
  });
  modal(
    operation === "qualify-sample"
      ? "Begrenzter Bandtest"
      : operation === "qualify"
        ? "Band vollständig testen"
        : "Band löschen",
    `${note("DESTRUKTIV: Sämtliche vorhandenen Daten auf diesem Medium werden unbrauchbar. Ausschließlich ausdrücklich freigegebene Test- oder Löschmedien verwenden.", "warning")}<dl class="detail-list" style="margin-top:20px"><dt>Laufwerk</dt><dd>${esc(approval.drive.serial)}</dd><dt>Medium</dt><dd>${esc(approval.drive.medium_serial)}</dd><dt>Aktion</dt><dd>${esc(operation)}</dd></dl><p>${operation === "qualify-sample" ? "Rekonstruierbare Testdaten: maximal 256 GiB oder 50 Minuten Schreiben, danach vollständige Rücklesung und SHA-256-Vergleich. SAMPLE_VERIFIED bestätigt ausschließlich den getesteten Bereich, keine Vollqualifikation. Der Vorgang kann länger dauern, wenn das Laufwerk langsam liest oder Fehler meldet." : operation === "qualify" ? "Rekonstruierbare Testdaten werden bis zum regulären Bandende geschrieben und anschließend vollständig zurückgelesen. Nur identische Datenmenge und SHA-256 ergeben VERIFIED. Der Vorgang kann mehrere Stunden dauern." : "Kurzlöschen setzt das logische Bandende zurück. Langlöschen führt das lange Löschkommando des Laufwerks aus. Beide Verfahren sind keine zertifizierte Datenvernichtung."}</p><p>Zur einmaligen Freigabe innerhalb von fünf Minuten exakt eingeben:</p><p class="mono">${esc(approval.confirmation)}</p><form id="maintenance-form"><label>Bestätigung<input name="confirmation" required autocomplete="off"></label><label class="check-label" style="margin-top:18px"><input name="destructive_confirmed" type="checkbox" required>Ich gebe genau dieses Medium zum vollständigen Überschreiben bzw. Löschen frei.</label><div class="form-actions"><button class="button primary" type="submit">Destruktiven Vorgang freigeben</button></div></form>`,
  );
  $("#maintenance-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = new FormData(e.target),
      button = $("button[type=submit]", e.target);
    button.disabled = true;
    try {
      await enqueue("tape-maintenance", {
        approval_id: approval.id,
        confirmation: d.get("confirmation"),
        destructive_confirmed: d.has("destructive_confirmed"),
      });
      closeModal();
      await render();
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
async function targetDialog(ident = "") {
  const r = await api("/replication");
  const t = r.targets.find((v) => v.id === ident) || {
    id: newId(),
    label: "",
    kind: "catalog",
    address: "",
    enabled: true,
    interval: 300,
  };
  modal(
    ident ? "Ziel bearbeiten" : "Optionales Ziel hinzufügen",
    `<p>Ein Katalogdienst stellt eine eigene Suchoberfläche bereit. Ein Snapshot-Verzeichnis bewahrt konsistente Datenbankkopien auf einem frei gewählten Datenträger oder einer eingehängten Freigabe auf.</p><form id="target-form"><div class="form-grid"><label>Bezeichnung<input name="label" maxlength="100" value="${esc(t.label)}" required></label><label>Typ<select name="kind"><option value="catalog" ${t.kind === "catalog" ? "selected" : ""}>Katalogdienst</option><option value="directory" ${t.kind === "directory" ? "selected" : ""}>Snapshot-Verzeichnis</option></select></label><label class="full">Basis-URL oder absoluter Verzeichnispfad<input name="address" value="${esc(t.address)}" placeholder="https://katalog.example oder /mnt/katalog-backup" required></label><label>Intervall in Sekunden<input name="interval" type="number" min="30" max="86400" value="${t.interval}" required></label><label>Geheimer Zielschlüssel<input name="key" type="password" autocomplete="new-password" maxlength="1024" ${t.key_configured ? 'placeholder="Leer lassen zum Beibehalten"' : 'minlength="32" required'}></label><label class="check-label"><input type="checkbox" name="enabled" ${t.enabled ? "checked" : ""}>Ziel aktivieren</label><label class="check-label"><input type="checkbox" name="allow_http" ${t.allow_http ? "checked" : ""}>Internes HTTP ausdrücklich erlauben</label></div><p class="hint">Katalogdienst: derselbe Schlüssel muss am Empfänger hinterlegt sein, dessen Herausgeber-ID muss ${esc(state.node.id)} lauten. Verzeichnis: bestehenden Mount prüfen und danach einmalig den Zielmarker bestätigen. Es werden keine Verzeichnisse angelegt und keine vorhandenen Snapshots überschrieben.</p><div class="form-actions"><button class="button primary" type="submit">Ziel speichern</button></div></form>`,
  );
  $("#target-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    const button = $("button[type=submit]", e.target);
    button.disabled = true;
    try {
      await api("/replication/targets/" + t.id, {
        method: "PUT",
        body: JSON.stringify({
          label: d.get("label"),
          kind: d.get("kind"),
          address: d.get("address"),
          interval: Number(d.get("interval")),
          key: d.get("key"),
          enabled: d.has("enabled"),
          allow_http: d.has("allow_http"),
        }),
      });
      closeModal();
      await refreshBase();
      await render();
      toast("Ziel gespeichert.");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
async function targetAction(ident, initialize = false) {
  modal(
    initialize ? "Snapshot-Verzeichnis freigeben" : "Ziel entfernen",
    `<p>${initialize ? "Prüfe, dass das konfigurierte Verzeichnis auf dem gewünschten Datenträger liegt. Diese Freigabe legt ausschließlich einen OTAM-Zielmarker an. Ein bestehender Marker wird nicht ersetzt." : "Dieses Ziel wird aus der Synchronisation entfernt. Bereits veröffentlichte Kataloge und Sicherungsdateien bleiben erhalten."}</p><p>Zur Bestätigung die Node-ID eingeben:</p><p class="mono">${esc(state.node.id)}</p><form id="target-action"><label>Node-ID<input name="confirmation" required autocomplete="off"></label><div class="form-actions"><button class="button primary" type="submit">${initialize ? "Zielmarker anlegen" : "Ziel entfernen"}</button></div></form>`,
  );
  $("#target-action").addEventListener("submit", async (e) => {
    e.preventDefault();
    const confirmation = new FormData(e.target).get("confirmation");
    if (confirmation !== state.node.id)
      return toast("Node-ID stimmt nicht überein.", true);
    const b = $("button[type=submit]", e.target);
    b.disabled = true;
    try {
      await api(
        "/replication/targets/" + ident + (initialize ? "/initialize" : ""),
        {
          method: initialize ? "POST" : "DELETE",
          body: JSON.stringify(initialize ? { confirmation } : {}),
        },
      );
      closeModal();
      await refreshBase();
      await render();
    } catch (error) {
      toast(error.message, true);
    } finally {
      b.disabled = false;
    }
  });
}
function newUser() {
  modal("Benutzer hinzufügen", `<p>Jedes Konto gilt nur auf diesem Node. Administratoren verwalten Konten und Hardwarewartung; Operatoren bedienen Archivjobs; Benutzer mit Leserechten durchsuchen den Katalog.</p>
    <form id="new-user-form"><div class="form-grid"><label>Benutzername<input name="username" pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,63}" maxlength="64" autocomplete="off" required></label><label>Berechtigung<select name="role"><option value="viewer">Nur lesen</option><option value="operator">Operator</option><option value="admin">Administrator</option></select></label><label class="full">Passwort<input name="password" type="password" autocomplete="new-password" minlength="12" required><small class="hint">Mindestens 12 Zeichen</small></label></div><div class="form-actions"><button class="button primary" type="submit">Benutzer hinzufügen</button></div></form>`);
  $("#new-user-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = new FormData(e.target), b = $("button[type=submit]", e.target);
    b.disabled = true;
    try {
      await api("/users", { method: "POST", body: JSON.stringify({ username: d.get("username"), password: d.get("password"), role: d.get("role") }) });
      closeModal(); await render(); toast("Benutzer angelegt.");
    } catch (error) { toast(error.message, true); b.disabled = false; }
  });
}
async function editUser(id, resetPassword = false) {
  const users = (await api("/users")).items;
  const user = users.find((u) => u.id === id);
  if (!user) throw Error("Benutzer nicht gefunden");
  if (resetPassword) {
    modal("Passwort setzen", `<p><strong>${esc(user.username)}</strong></p><form id="user-password-form"><label>Neues Passwort<input name="password" type="password" autocomplete="new-password" minlength="12" required><small class="hint">Mindestens 12 Zeichen. Andere Sitzungen des Kontos werden beendet.</small></label><div class="form-actions"><button class="button primary" type="submit">Passwort setzen</button></div></form>`);
    $("#user-password-form").addEventListener("submit", async (e) => {
      e.preventDefault(); const b = $("button[type=submit]", e.target); b.disabled = true;
      try {
        await api("/users/" + encodeURIComponent(id), { method: "PATCH", body: JSON.stringify({ password: new FormData(e.target).get("password") }) });
        closeModal(); await render(); toast("Passwort geändert.");
      } catch (error) { toast(error.message, true); b.disabled = false; }
    });
    return;
  }
  modal("Benutzer bearbeiten", `<p><strong>${esc(user.username)}</strong></p><form id="edit-user-form"><div class="form-grid"><label>Berechtigung<select name="role"><option value="viewer" ${user.role === "viewer" ? "selected" : ""}>Nur lesen</option><option value="operator" ${user.role === "operator" ? "selected" : ""}>Operator</option><option value="admin" ${user.role === "admin" ? "selected" : ""}>Administrator</option></select></label><label class="check-label"><input type="checkbox" name="enabled" ${user.enabled ? "checked" : ""}>Konto aktiviert</label></div><p class="hint">Der letzte aktive Administrator kann nicht deaktiviert oder herabgestuft werden. Rollenänderungen beenden bestehende Sitzungen.</p><div class="form-actions"><button class="button primary" type="submit">Speichern</button></div></form>`);
  $("#edit-user-form").addEventListener("submit", async (e) => {
    e.preventDefault(); const d = new FormData(e.target), b = $("button[type=submit]", e.target); b.disabled = true;
    try {
      await api("/users/" + encodeURIComponent(id), { method: "PATCH", body: JSON.stringify({ role: d.get("role"), enabled: d.has("enabled") }) });
      closeModal(); await render(); toast("Benutzer aktualisiert.");
    } catch (error) { toast(error.message, true); b.disabled = false; }
  });
}
function bindForms(root = $("#content")) {
  const on = (id, handler) => {
    const f = $(id, root);
    if (f)
      f.addEventListener("submit", async (e) => {
        e.preventDefault();
        const button = $("button[type=submit]", f);
        if (button) button.disabled = true;
        try {
          await handler(new FormData(f), f);
        } catch (err) {
          toast(err.message, true);
        } finally {
          if (button) button.disabled = false;
        }
      });
  };
  on("#mode-form", async (d) => {
    await api("/operation-mode", {
      method: "PUT",
      body: JSON.stringify({ mode: d.get("mode") }),
    });
    await refreshBase();
    await render();
    toast("Betriebsart übernommen. Es wurde kein Band verändert.");
  });
  on("#plan-form", async (d) => {
    await enqueue("plan", {
      source_id: d.get("source_id"),
      media_id: d.get("media_id"),
      target: Math.round(Number(d.get("target")) * 1e9),
      staging_id: d.get("staging_id"),
    });
    location.hash = "jobs";
  });
  on("#medium-form", async (d) => {
    await enqueue("create-medium", {
      label: d.get("label"),
      capacity: Math.round(Number(d.get("capacity")) * 1e9),
      media_class: d.get("media_class"),
    });
    closeModal();
    await render();
  });
  on("#backup-form", async (d, f) => {
    if (d.get("confirmation") !== f.dataset.job)
      throw new Error("Die eingegebene Job-ID stimmt nicht überein.");
    await enqueue("backup", {
      job_id: f.dataset.job,
      confirm: d.get("confirmation"),
      plan_hash: f.dataset.hash,
      resume: f.dataset.resume === "true",
      prepare_all: d.get("prepare_all") === "on",
    });
    closeModal();
    location.hash = "jobs";
    await render();
  });
  on("#revalidate-form", async (d, f) => {
    if (d.get("confirmation") !== f.dataset.job)
      throw new Error("Job-ID stimmt nicht überein.");
    await enqueue("stage", {
      job_id: f.dataset.job,
      revalidate_ready: true,
      confirm: d.get("confirmation"),
    });
    closeModal();
    location.hash = "staging";
    await render();
  });
  on("#verify-form", async (d) => {
    await enqueue("verify", { media_id: d.get("media_id") });
    location.hash = "jobs";
  });
  on("#catalog-form", async (d) => {
    const f = {
      q: d.get("q"),
      file_type: d.get("file_type"),
      media_id: d.get("media_id"),
      checksum: d.get("checksum"),
      state: d.get("state"),
      duplicates: d.get("duplicates") === "on",
      archive_id: state.filters.archive_id || "",
    };
    for (const [key, name] of [
      ["min_size", "min_mb"],
      ["max_size", "max_mb"],
    ])
      if (d.get(name) !== "") f[key] = Math.round(Number(d.get(name)) * 1e6);
    for (const [key, name] of [
      ["after", "after_date"],
      ["before", "before_date"],
    ])
      if (d.get(name)) {
        f[name] = d.get(name);
        f[key] = Math.round(
          new Date(
            d.get(name) + (key === "before" ? "T23:59:59.999" : "T00:00:00"),
          ).getTime() * 1e6,
        );
      }
    state.filters = f;
    state.offset = 0;
    await render();
  });
  on("#own-password-form", async (d, form) => {
    await api("/account/password", { method: "POST", body: JSON.stringify({
      current_password: d.get("current_password"), new_password: d.get("new_password"),
    }) });
    form.reset();
    toast("Passwort geändert. Andere Sitzungen wurden beendet.");
  });
  const languageSelect = $("#language-select", root);
  if (languageSelect) languageSelect.addEventListener("change", async () => {
    const previous = getLanguage();
    languageSelect.disabled = true;
    try {
      const user = await api("/account/locale", { method: "PUT", body: JSON.stringify({ locale: languageSelect.value }) });
      state.account = { ...state.account, ...user };
      setLanguage(user.locale);
      await refreshBase();
      await render();
    } catch (error) {
      languageSelect.value = previous;
      toast(error.message, true);
    } finally { languageSelect.disabled = false; }
  });
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest(
    "button,[data-archive-files],[data-media-files],[data-copies]",
  );
  if (!b) return;
  try {
    if (b.dataset.maintenanceDrive)
      await maintenanceDialog(b.dataset.maintenanceDrive, b.dataset.operation);
    else if (b.dataset.editUser) await editUser(b.dataset.editUser);
    else if (b.dataset.passwordUser) await editUser(b.dataset.passwordUser, true);
    else if (b.dataset.removeResource) {
      modal(
        "Verzeichnis abmelden",
        `<p>Die Ressource wird aus der Auswahl entfernt. Bestehende Dateien bleiben erhalten; gebundene Jobs und unverifizierte Archive verhindern die Abmeldung.</p><button class="button primary" id="remove-resource-confirm" data-resource="${esc(b.dataset.removeResource)}">Ressource abmelden</button>`,
      );
    } else if (b.dataset.editTarget) await targetDialog(b.dataset.editTarget);
    else if (b.dataset.deleteTarget) await targetAction(b.dataset.deleteTarget);
    else if (b.dataset.initTarget)
      await targetAction(b.dataset.initTarget, true);
    else if (b.dataset.job) await showJob(b.dataset.job);
    else if (b.dataset.stage) {
      await enqueue("stage", { job_id: b.dataset.stage });
      closeModal();
      location.hash = "staging";
      await render();
    } else if (b.dataset.backup) await confirmBackup(b.dataset.backup);
    else if (b.dataset.revalidate) {
      const ident = b.dataset.revalidate;
      modal(
        "Staging ausdrücklich erneut prüfen",
        `<p>OTAM prüft das ursprüngliche TAR vollständig gegen den gespeicherten Hash und das Dateimanifest. Geänderte Inhalte, eine ausgetauschte Datei oder ein bereits versuchter Bandschreibvorgang werden nicht freigegeben.</p><p class="mono">${esc(ident)}</p><form id="revalidate-form" data-job="${esc(ident)}"><label>Job-ID zur Bestätigung<input name="confirmation" required autocomplete="off"></label><div class="form-actions"><button class="button primary" type="submit">Vollständig erneut prüfen</button></div></form>`,
      );
      bindForms($("#modal"));
    } else if (b.dataset.resume) await confirmBackup(b.dataset.resume, true);
    else if (b.dataset.verify) {
      modal(
        "Medium vollständig prüfen",
        `<p>Alle Archive auf <strong>${esc(mediaName(b.dataset.verify))}</strong> werden vollständig zurückgelesen und gegen ihre Manifeste und Prüfsummen geprüft.</p><div class="button-row"><button class="button primary" data-confirm-verify="${esc(b.dataset.verify)}">${icon("shield")}Prüfung starten</button></div>`,
      );
    } else if (b.dataset.confirmVerify) {
      await enqueue("verify", { media_id: b.dataset.confirmVerify });
      closeModal();
      location.hash = "integrity";
    } else if (b.dataset.archiveFiles) {
      state.filters = { archive_id: b.dataset.archiveFiles };
      state.offset = 0;
      location.hash = "catalog";
      if (state.page === "catalog") await render();
    } else if (b.dataset.mediaFiles) {
      state.filters = { media_id: b.dataset.mediaFiles };
      state.offset = 0;
      location.hash = "catalog";
    } else if (b.dataset.copies) {
      state.filters = { checksum: b.dataset.copies };
      state.offset = 0;
      state.advanced = true;
      await render();
    } else if (b.dataset.restoreGroup)
      await restoreGroup(b.dataset.restoreGroup);
    else if (b.dataset.mediumTools) {
      const id = b.dataset.mediumTools;
      modal(
        "Medien-Werkzeuge · " + mediaName(id),
        `<p>Diese Aktionen lesen und prüfen das Simulatormedium. Sie überschreiben keine vorhandenen Banddateien.</p><div class="button-row"><button class="button" data-recover="${esc(id)}">Unterbrochene Jobs erfassen</button><button class="button" data-rebuild="${esc(id)}">Katalog aus Medium rekonstruieren</button></div>`,
      );
    } else if (b.dataset.recover || b.dataset.rebuild) {
      await enqueue(b.dataset.recover ? "recover" : "rebuild", {
        media_id: b.dataset.recover || b.dataset.rebuild,
      });
      closeModal();
      location.hash = "jobs";
    } else
      switch (b.id) {
        case "new-medium":
          newMedium();
          break;
        case "new-user":
          newUser();
          break;
        case "modal-close":
          closeModal();
          break;
        case "new-source":
          await resourceDialog("source");
          break;
        case "new-staging":
          await resourceDialog("staging");
          break;
        case "scan-drives":
          await enqueue("hardware-scan", {});
          break;
        case "remove-resource-confirm":
          await api("/storage-resources/" + b.dataset.resource, {
            method: "DELETE",
            body: "{}",
          });
          closeModal();
          await refreshBase();
          await render();
          break;
        case "new-target":
          await targetDialog();
          break;
        case "sync-now":
          await enqueue("sync", {});
          break;
        case "filter-toggle":
          state.advanced = !state.advanced;
          $(".advanced-filters").hidden = !state.advanced;
          b.setAttribute("aria-expanded", state.advanced);
          break;
        case "clear-filters":
          state.filters = {};
          state.offset = 0;
          await render();
          break;
        case "prev-page":
          state.offset = Math.max(0, state.offset - 50);
          await render();
          break;
        case "next-page":
          state.offset += 50;
          await render();
          break;
        case "clear-selection":
          state.selection.clear();
          await render();
          break;
        case "download-selection":
          downloadSelection();
          break;
        case "retry":
          await refreshBase();
          await render();
          break;
        case "nav-toggle": {
          const open = $("#sidebar").classList.toggle("open");
          $("#nav-backdrop").hidden = !open;
          b.setAttribute("aria-expanded", open);
          break;
        }
      }
  } catch (err) {
    toast(err.message, true);
  }
});
document.addEventListener("change", (e) => {
  if (e.target.classList.contains("file-select")) {
    const f = state.files[Number(e.target.dataset.index)],
      key = f.archive_id + ":" + f.path;
    if (e.target.checked) state.selection.set(key, f);
    else state.selection.delete(key);
    $("#selection-bar").innerHTML = selectionBar();
  } else if (e.target.id === "select-page") {
    $$(".file-select").forEach((el) => {
      el.checked = e.target.checked;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
});
$("#nav-backdrop").addEventListener("click", () => {
  $("#sidebar").classList.remove("open");
  $("#nav-backdrop").hidden = true;
  $("#nav-toggle").setAttribute("aria-expanded", "false");
});
window.addEventListener("hashchange", () => {
  $("#sidebar").classList.remove("open");
  $("#nav-backdrop").hidden = true;
  $("#nav-toggle").setAttribute("aria-expanded", "false");
  if (state.node) render();
});
$("#modal").addEventListener("click", (e) => {
  if (e.target === $("#modal")) {
    const r = $("#modal").getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      closeModal();
  }
});
function showLogin() {
  document.title = translate("OTAM · Dein Langzeitarchiv");
  $("#shell").hidden = true;
  $("#login").hidden = false;
  state.csrf = "";
  state.node = null;
  state.account = null;
  paintIcons($("#login"));
}
async function start() {
  await refreshBase();
  $("#login").hidden = true;
  $("#shell").hidden = false;
  if (state.account) {
    $("#username").textContent = state.account.username;
    $(".account-button .avatar").textContent = state.account.username.slice(0, 1).toUpperCase();
  }

  paintIcons();
  localize(document);
  await render();
}
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const d = new FormData(e.target),
    b = $("button", e.target);
  b.disabled = true;
  $("#login-error").textContent = "";
  try {
    const r = await api("/login", {
      method: "POST",
      body: JSON.stringify({
        username: d.get("username"),
        password: d.get("password"),
      }),
    });
    state.csrf = r.csrf;
    state.account = r;
    setLanguage(r.locale);
    $("#username").textContent = r.username;
    e.target.elements.password.value = "";
    await start();
  } catch (err) {
    $("#login-error").textContent = err.message;
  } finally {
    b.disabled = false;
  }
});
$("#logout").addEventListener("click", async () => {
  try {
    await api("/logout", { method: "POST", body: "{}" });
    state.selection.clear();
    showLogin();
  } catch (err) {
    toast(err.message, true);
  }
});
setInterval(async () => {
  if (!state.node || state.polling || document.hidden) return;
  state.polling = true;
  try {
    await refreshBase();
    if (
      ["dashboard", "jobs", "staging", "integrity", "sync", "logs"].includes(
        state.page,
      ) &&
      !$("#modal").open &&
      !document.activeElement.matches(
        "input, select, textarea, [contenteditable=true]",
      )
    )
      await render();
  } catch (err) {
    $("#connection-label").textContent = "Verbindung unterbrochen";
    $("#connection-dot").classList.add("off");
  } finally {
    state.polling = false;
  }
}, 5000);
(async () => {
  paintIcons();
  localize(document);
  try {
    const r = await api("/session");
    state.csrf = r.csrf;
    state.account = r;
    setLanguage(r.locale);
    await start();
  } catch (e) {
    showLogin();
  }
})();

document.addEventListener("otam:unauthorized", showLogin);
