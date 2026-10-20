# Node-Konfiguration der Webmodule

UTF-8-JSON, erzeugt durch `otam web-init`. Kein Laufzeit-Neuladen: Änderungen nach Sicherung der Konfiguration und kontrolliertem Dienstneustart. Unbekannte Felder werden abgelehnt. Konfiguration und Peer-Schlüssel nicht in Git aufnehmen.

| Feld | Bedeutung / Standard |
|---|---|
| node_id | Eindeutige UUID dieses Nodes, dauerhaft beibehalten |
| name | Anzeigename in Oberfläche und Modulstatus |
| role | `archive` oder `catalog`; der Catalog Node hat keine Archivierungsrouten |
| state | Absoluter lokaler persistenter Ordner für Steuerdatenbank und Snapshots |
| catalog | Lokaler Primärkatalog auf dem Archive Node; auf dem Catalog Node ungenutzter separater Pfad |
| staging | Absoluter lokaler Staging-Pfad; niemals Quelle oder Katalog einschließen |
| media_root | Ausschließlich für OTAM-Simulatormedien reservierter Ordner; keine `/dev`-Geräte |
| restore_root | Basis für neue Restore-Zielordner; Browser wählt nur einen sicheren Unterordnernamen |
| password | Gesalzener PBKDF2-SHA-256-Hash, 600.000 Runden; kein Klartext |
| username | Administrativer Benutzername, Standard `admin` |
| host | Bind-Adresse; Standard `127.0.0.1`; interne Adresse nur ausdrücklich konfigurieren |
| port | HTTP-Port, Standard `8765` |
| allowed_hosts | Explizite erlaubte Hostnamen/IPs ohne Schema/Port, kein `*`; standardmäßig localhost/127.0.0.1/IPv6-Loopback |
| sources | Liste mit eindeutigen `id`, `label`, absoluten `path`; nur Archive Node, keine beliebigen Browserpfade |
| peer_url | Feste Basisadresse des Catalog Node, standardmäßig leer; HTTPS, kein Redirect-Folgen |
| peer_key_file | Lokale reguläre Schlüsseldatei, kein Symlink, Modus 0600, mindestens 32 zufällige ASCII-Bytes |
| publisher_id | Auf Catalog Node exakt die Archive-Node-UUID des erlaubten Herausgebers |
| allow_http_peer | Standard `false`; ausschließlich für bewusst gewählten internen/WireGuard-HTTP-Transport aktivieren |
| sync_interval | 30–86.400 Sekunden, Standard `300`; nur laufender Archive-Worker plant Übertragungen |
| nas_backup | Bereits gemounteter Snapshot-Zielordner mit `.otam-backup-target`; standardmäßig kein NAS-Export |
| max_snapshot_bytes | Standard 1 GiB; absolute Übertragungsgrenze, höchstens 100 GiB konfigurierbar |
| session_seconds | 300–86.400 Sekunden, Standard acht Stunden; feste Ablaufzeit |
| secure_cookie | Standard `false` für localhost-HTTP; bei HTTPS `true` |
| trusted_proxy_ips | Standard leer. Nur explizite IPs eines internen TLS-Proxys akzeptieren Forwarded-Header |

Quellen müssen außerhalb von Katalog, Steuerdaten, Staging, Medienbereich und Restore liegen. Beispiele verwenden Ressourcen-IDs statt serverseitiger Freitext-Pfade. Dateisystemberechtigungen sind zusätzlich erforderlich; die Anwendung setzt keine NAS-Quellrechte und verändert keine Originaldateien.

## Rollen und API

Alle Katalog- und Betriebsendpunkte erfordern eine gültige HttpOnly-Sitzung. Bei Mutationen zusätzlich `X-CSRF-Token`; Token erhält der angemeldete Client über `GET /api/v1/session`. Keine Tokens in URL-Parametern. `POST /api/v1/login` nimmt JSON `username` und `password`; `POST /api/v1/logout` beendet die Sitzung. Ein Login wird nach zehn Fehlversuchen je Client-IP für das verbleibende 15-Minuten-Fenster begrenzt.

| Ressource | Zweck |
|---|---|
| GET /healthz | Minimale unauthentifizierte Betriebsprüfung ohne Dateipfade oder Katalogdaten |
| GET /api/v1/node | Rolle, Fähigkeiten, Quellen-IDs, Katalogstand, Worker-Heartbeat |
| GET /api/v1/overview | Aggregierte reale Katalogzahlen |
| GET /api/v1/media | Medieninventar, auf Archive Node eingebundene Simulatoren |
| GET /api/v1/archives | Archivübersicht mit `limit` und `offset` |
| GET /api/v1/files | Filter `q`, `checksum`, `file_type`, `media_id`, `archive_id`, `state`, `min_size`, `max_size`, `after`, `before`, `duplicates`, `limit`, `offset` |
| GET /api/v1/source-tree | Dateibrowser innerhalb einer freigegebenen Quelle; `source_id`, relativer `path`, `offset` |
| GET /api/v1/jobs und /jobs/{id} | Jobliste und geprüfter Plan ohne vollständige Manifest-Dateiliste in der Übersicht |
| GET /api/v1/staging | Persistente Archivphasen; lokale Kapazität ausschließlich auf Archive Node |
| GET /api/v1/events | Ereignisse, optional `job_id`, `before`, `limit` |
| GET /api/v1/verifications | Prüfresultate |
| GET /api/v1/export | Streamender JSON-/CSV-Export einer freigegebenen Tabelle |
| GET /api/v1/replication | Letzter veröffentlichter/empfangener Stand und Übertragungsverlauf |
| GET /api/v1/commands | Nur Archive Node: persistente Webaufträge |
| POST /api/v1/commands | Nur Archive Node: `kind`, `payload`; zusätzlicher `Idempotency-Key` erforderlich |
| POST /api/v1/restore-plan | Nur Archive Node: serverseitige Prüfung der Auswahl und neuer Zielname |
| GET /api/v1/hardware | Nur Archive Node: lesende Erkennung |
| PUT /api/v1/replication/snapshot | Nur Catalog Node: eigener Peer-Bearer plus signiertes Manifest; kein Sessionzugang |

Befehlsarten: `create-medium`, `plan`, `stage`, `backup`, `backup-set`, `verify`, `restore`, `recover`, `rebuild`, `sync`. `plan` akzeptiert `selected_paths` (relative Dateien/Ordner), `verify_mode` (`archive` oder `media`) und entweder `media_id` oder geordnete `media_ids`. `backup-set` bestätigt je Medium `job_id`, `confirm`, `plan_hash` und `media_id`. HTTP 202 bedeutet angenommen, nicht abgeschlossen. Über `/commands` und den referenzierten Kernjob das Ergebnis prüfen. `backup` verlangt Job-ID sowohl in `job_id` als auch `confirm` und den geprüften `plan_hash`. `resume` ist ein ausdrücklicher boolescher Parameter. `stage` mit `revalidate_ready=true` verlangt ebenfalls `confirm=job_id`; es ist kein Weg zur Akzeptanz geänderter TAR-Inhalte. Ein identischer Idempotency-Key gibt denselben Auftrag zurück; andere Nutzdaten mit demselben Key werden abgelehnt.

Dateisuchgrößen sind Bytes, `after`/`before` Änderungszeitpunkte in Unix-Nanosekunden. Pagination maximal 200 Treffer pro API-Seite. CSV-Export entschärft Tabellenformeln; JSON bewahrt die ursprünglichen Dateinamen.

## Replikationszustände

Der Herausgeber zählt Snapshots persistent, auch wenn eine Übertragung fehlschlägt; Sequenzlücken sind zulässig. Gleiche Sequenz und gleicher Inhalt: idempotent. Gleiche Sequenz mit anderem Inhalt oder eine kleinere Sequenz: verweigert. Neue Snapshots werden zunächst vollständig in eine eigene `.partial`-Datei geschrieben und vor Veröffentlichung geprüft. Frühere aktive Snapshot-Dateien bleiben erhalten. Nur die kleine aktive Referenz wird transaktional umgestellt; ein Dateipublikations-Crash hinterlässt höchstens ein noch nicht aktives Artefakt, das eine identische Wiederholung erkennen kann.

Optionale Ziele werden unabhängig veröffentlicht. Eine fehlgeschlagene Übertragung blockiert die weiteren Ziele nicht; der Sammelauftrag meldet Fehler und erhält die Einzelresultate. Wiederholungen überspringen bereits bestätigte unveränderte Kataloge pro Ziel. Geheimnisse erscheinen nicht in den Übertragungsprotokollen.

## Optionale Ziele über Weboberfläche / REST

Der lokale Archive-Node-Katalog ist immer vorhanden und nicht abwählbar. Zusätzliche Ziele sind standardmäßig leer und keine Betriebsvoraussetzung. Unter **Synchronisation → Ziel hinzufügen** können mehrere Katalogdienste und Snapshot-Verzeichnisse eingerichtet, bearbeitet, deaktiviert oder entfernt werden. Änderungen gelten ohne Dienstneustart. Ein reines Snapshot-Ziel bietet selbst keine Such-Weboberfläche; dafür einen Catalog Node betreiben.

- `GET /api/v1/replication`: `local_catalog`, `targets` mit Einzelstatus, Metadaten und Verlauf. Kein Schlüsselinhalt oder Schlüsseldateipfad.
- `PUT /api/v1/replication/targets/{uuid}`: `{label,kind,address,enabled,interval,allow_http,key}`. Typ `catalog` erwartet eine HTTPS-Basisadresse; internes HTTP benötigt `allow_http: true`. Typ `directory` erwartet einen absoluten getrennten Verzeichnispfad. `interval` in Sekunden (30–86400). `key`: 32–1024 druckbare ASCII-Zeichen ohne Leerzeichen; bei Bearbeitung leer lassen, um den bisherigen Schlüssel beizubehalten.
- `POST /api/v1/replication/targets/{uuid}/initialize`: `{confirmation: "ARCHIVE_NODE_UUID"}`. Explizites erstmaliges Anlegen des Zielmarkers in einem bestehenden Verzeichnis, kein automatisches Mounten oder Ersetzen eines vorhandenen Markers.
- `DELETE /api/v1/replication/targets/{uuid}`: Entfernt nur die Veröffentlichungskonfiguration, keine übertragenen Kataloge oder Sicherungsdateien. Web-Middleware verlangt auch hier einen JSON-Body (z. B. `{}`) sowie CSRF-Token und gültige Sitzung.

Alle Änderungen nur am Archive Node, authentifiziert und mit CSRF-/Origin-Schutz. Am Empfänger werden dessen Herausgeber-ID und Empfangsschlüssel weiterhin über die geschützte Node-Konfiguration festgelegt. Betriebssystem-Mounts, Dienstrechte und TLS-Termination werden nicht durch die Zielverwaltung eingerichtet.

`peer_url`, `nas_backup`, `allow_http_peer` und `sync_interval` sind abwärtskompatible Startwerte für bestehende Installationen. Nach der ersten Bearbeitung der Zielliste ist diese persistent maßgeblich. `peer_key_file` bleibt unabhängig davon die Empfangskonfiguration des Catalog Node. Die lokale Steuerdatenbank enthält private Zielschlüssel und darf nicht öffentlich geteilt oder in Katalogexporte aufgenommen werden.

## Quellen, Staging und physische Wartung

`directory_roots`: Liste absoluter, administrativ freigegebener Verzeichnisbereiche für den Picker. Standard leer; bestehende Quellen und Standard-Staging bleiben auswählbar. Kein pauschaler Zugriff auf `/`. Verzeichnisse/Mounts müssen vorher vorhanden und für das Dienstkonto zugänglich sein. Zusätzliche schreibbare Staging-Ziele müssen außerdem in den systemd-`ReadWritePaths` beider Dienste freigegeben werden; dies geschieht nicht aus der Webanwendung.

`physical_maintenance`: Standard `false`. Ermöglicht nach administrativer Einrichtung der Worker-Geräterechte den expliziten Wechsel zwischen Simulator und physischem Wartungsbetrieb unter Hardware. Reguläre echte LTO-Archivierung wird dadurch nicht freigeschaltet; `LinuxTape` bleibt bis zur Bandformat-Abnahme gesperrt.

`physical_archiving`: Standard `false`, nur zusammen mit `physical_maintenance=true`
auf einem Archive Node zulässig. Separates Gate für den neuen regulären physischen
Workerpfad; bis zum Ende der Abnahme nicht in der Installation aktivieren.
Der Betriebsmodus muss zusätzlich `physical` sein. Gerätezugriffe bleiben im
Worker; HTTP-Anfragen prüfen ausschließlich dessen gespeicherte Erkennung.

Unter **Hardware** kann ein Administrator ein vorhandenes selbstbeschreibendes
OTAM-Medium lesend registrieren. Der neue Auftrag `register-physical` benötigt
`{drive_id, drive_serial, medium_serial}`. Der Worker erkennt die Hardware frisch,
liest Header und Belege und speichert eine Bindung aus OTAM-Medien-UUID,
Laufwerksseriennummer und MAM-Seriennummer. `/dev/nst*` wird nicht dauerhaft
als Identität gespeichert. Es gibt keine automatische Initialisierung. Ein
unbekannter Header scheitert; zum Import unbekannter Archive folgt anschließend
eine ausdrückliche vollständige Katalogrekonstruktion.

Vor `backup` müssen gespeicherte Transferwerte zum ausgewählten Staging, frisch
erkannten Laufwerksprofil und Dateisystem-Fingerprint passen. Rate und Puffer
werden tatsächlich an `LinuxTape`/mbuffer übergeben. `transfer_policy_selected`
protokolliert die Auswahl; die tatsächlichen Write-Samples protokollieren die
wirksamen Werte. Das historische Feld `effective=false` bezeichnet keine globale
Geräteeinstellung: Werte werden je Job erneut validiert. Staging bleibt nach
Planung auch ohne eingelegtes Medium möglich.

`physical_multivolume`: Standard `false`, nur zusammen mit
`physical_archiving=true` zulässig. Separates Gate des neuen physischen
Mehrbandkandidaten. Bis zur realen Medienwechselabnahme nicht aktivieren.
Simulator-Mehrbandjobs bleiben verfügbar. Physische Initialisierung hat
unabhängig davon ein eigenes Gate; es wird niemals automatisch formatiert.

`physical_initialization`: Standard `false`, nur zusammen mit
`physical_archiving=true` zulässig. Der neue Adminworkflow initialisiert
ausschließlich lokal nicht registrierte MAM-Kassetten nach separatem Review.
Auch deren unbekannter vorhandener Inhalt wird unbrauchbar. Bekannte Kassetten
aller Klassen/Zustände und ungeklärte Schreibintents sind gesperrt. Nach
Katalogverlust zuerst lesend registrieren und rekonstruieren.

`POST /api/v1/initialization/prepare` verlangt Admin/CSRF und
`{drive_id, drive_serial, medium_serial, label, media_class}`. Native Kapazität
kommt aus dem bestätigten Profil, nicht aus einem Eingabefeld. Rückgabe enthält
konkreten Review, Grant-ID, fünf Minuten Gültigkeit und Phrase
`INITIALIZE <Drive-SN> <MAM-SN>`. Der Adminauftrag `initialize-physical` benötigt
anschließend nur `{approval_id, confirmation, destructive_confirmed: true}`.
Einmalige transaktionale Reservation, frische Identität, Geräte-/I/O-Sperren,
bestätigtes BOT und vollständiger Header-Readback sind verbindlich. INITIALIZED
bedeutet Headerinitialisierung, keine Datenarchivierung oder Vollqualifikation.
Keine automatische Wiederholung nach unsicherem Write. Gate bis zur realen
Abnahme geschlossen lassen. [Initialisierungsarchitektur](architecture/physical-initialization.md).

Physische Planung verwendet nun registrierte Katalogstände, ohne Gerät zu öffnen
oder das Band zu bewegen. Quelle, SHA-256 und vollständige TAR-Aufteilung werden
weiterhin inventarisiert. Nur gebundene READY/IN_USE-Medien mit konsistenten
VERIFIED-Archivfolgen, plausiblen Kapazitätsangaben und ohne bekannten lokalen
Pending-Marker sind planbar. Das ist eine Schätzung und keine Prüfung des
eingelegten Mediums. `/media` unterscheidet dafür `plannable`, `mounted` und
`backend`; eine nicht eingelegte physische Kassette kann planbar sein.

Bei separat freigegebenem Mehrbandbetrieb akzeptiert `plan` geordnete
`media_ids`. Ganze TARs werden auf die Medien verteilt; Dateien und TARs werden
nicht bandübergreifend geteilt. Unterschiedliche UUIDs mit derselben MAM-Identität
werden als doppelte Kassette abgewiesen. `backup-set` führt genau das nächste Kind aus
und verlangt die bestätigte Parent-Job-ID, den Planhash und die erwartete
Medien-UUID. Vor jedem Schritt werden Drive/MAM frisch erkannt, die gespeicherten
Transferwerte geprüft und reale Identität, EOD/Dateianzahl, Tail und Receiptfolge
gegen den Katalog kontrolliert. Ein veralteter Offlineplan erlaubt kein Append.
Der Schritt endet erst nach vollständiger Verifikation dieses Mediums als
WAITING_MEDIA beziehungsweise VERIFIED; es erfolgt kein automatischer Wechsel.
Bei verlorenem Parent-Abschluss nach bereits VERIFIED abgeschlossenen Kindern
werden Identität/EOD/Receipts erneut abgeglichen, ohne einen neuen Payload-Scrub
zu behaupten. Restore erfolgt weiterhin je ausgewählter Archiv-/Mediengruppe.

Der Kandidat ist softwareseitig gegen zwei emulierte physische Backends geprüft.
Dies ersetzt keine reale Zwei-Kassetten-Abnahme und ist keine Produktionsfreigabe.
Details: [Physischer Mehrbandbetrieb](architecture/physical-multivolume.md).

Die CLI verwendet dieselbe dauerhafte Workerwarteschlange:

```sh
otam physical-command --config /etc/otam/node.json --kind plan --payload-file plan.json
otam physical-command-status --config /etc/otam/node.json --command-id <command-uuid>
```

`plan.json` enthält z.B. `{ "media_id": "<media-uuid>", "source_id": "source-1",
"staging_id": "default-staging", "verify_mode": "media" }`.
Weitere erlaubte Arten: `register-physical`, `initialize-physical`, `stage`, `backup`, `backup-set`, `verify`, `restore`,
`recover`, `rebuild`. Für Backup sind `{job_id, confirm: job_id, plan_hash}` nach
Prüfung des persistenten Archivplans erforderlich. Restore akzeptiert
`{media_id, target_name, paths?, archive_id?}`. Wiederholte Aufrufe können denselben
`--idempotency-key` verwenden. Der CLI-Aufruf führt keine Geräteaktion selbst aus;
der laufende Worker validiert den Auftrag vor der Ausführung erneut.

`allow_host_shutdown`: Standard `false`, nur für Archive Nodes. Zeigt Administratoren unter **Einstellungen** den Shutdown-Knopf und erlaubt die bestätigte API-Anforderung. Die Webanwendung erhält dadurch keine root-Rechte. Für einen funktionsfähigen Shutdown müssen zusätzlich die beiden Vorlagen `packaging/systemd/otam-poweroff.path` und `otam-poweroff.service` als root installiert und die `.path`-Unit aktiviert werden. `PathExists` muss auf `<state>/poweroff.request` zeigen; `TMPDIR` der Helfer-Unit muss exakt mit Web und Worker übereinstimmen und dem OTAM-Dienstkonto gehören (0700). Die Vorlagen verwenden `/var/lib/otam/state` und `/var/lib/otam/tmp`. Bei anderen Installationspfaden die Units vor Aktivierung anpassen. Auf Catalog Nodes bleibt der Knopf verborgen.

Der POST auf `/api/v1/system/poweroff` benötigt eine Admin-Sitzung, gültiges CSRF-Token und `{confirmation: "<exakter Node-Name>"}`. Laufende oder wartende OTAM-Aufträge sowie eine gehaltene I/O-Sperre blockieren die Anforderung. Der root-Helfer akzeptiert nur eine frische, für den aktuellen Boot signalisierte Anforderung aus dem lokalen Steuerkatalog und stoppt den Worker vor dem festen `systemctl poweroff --no-wall`. Ein Fehlschlag entfernt die Anforderung, hebt die Auftragssperre auf und startet einen bereits gestoppten Worker erneut. Das Feature wurde nur mit gemockten `systemctl`-Aufrufen getestet; ein echter Shutdown muss bei einer späteren kontrollierten Wartung abgenommen werden.

- `GET /api/v1/directories?path=...`: begrenzte Auswahl vorhandener Unterverzeichnisse, keine Dateien oder geheimen Node-Verzeichnisse. Leerer Pfad zeigt freigegebene Bereiche.
- `GET /api/v1/storage-resources`: Quellen/Staging mit Verfügbarkeit, lokalen Dateisystemwerten und freien Bytes.
- `PUT /api/v1/storage-resources/{uuid}`: `{kind: "source"|"staging", label, path}`. Unveränderliche Registrierung; Staging lokal/schreibbar, Quellen und Node-Daten getrennt.
- `DELETE /api/v1/storage-resources/{id}`: nur Abmelden, keine Dateilöschung. Aktive Aufträge und nicht abgeschlossene Jobbindungen verhindern Abmeldung.
- Archivierungsplanung akzeptiert zusätzlich `staging_id`. Bei älteren Aufträgen bleibt `default-staging` gültig. Auswahl wird je Job gebunden.
- `PUT /api/v1/operation-mode`: `{mode: "simulator"|"physical"}`. Keine Bandaktion durch den Wechsel.
- `POST /api/v1/maintenance/prepare`: `{drive_id, operation: "qualify"|"erase-short"|"erase-long"}`. Liefert konkrete Identität, Ablaufzeit und erforderliche Bestätigungsphrase.
- Workerauftrag `tape-maintenance`: `{approval_id, confirmation, destructive_confirmed: true}`. Transaktional einmalige, fünf Minuten gültige Einzelfreigabe; Identität/Schreibschutz werden vor Hardwarezugriff erneut geprüft.
- Workerauftrag `hardware-scan`: `{}`. Automatische Erkennung erfolgt daneben etwa alle zehn Sekunden.

Optionale Workerrechte: `packaging/udev/70-otam-tape.rules` und `packaging/systemd/otam-worker-physical.conf`, eigene Gruppe `otam-tape`. Web bleibt mit privaten Geräten abgeschottet. Kein root-Webprozess, keine Disk-Gruppenmitgliedschaft. [Ablauf, Sicherheitsgrenzen und Abnahme](architecture/physical-maintenance.md).

## Ab 0.6.1: Abbruch-Reset und Hardwareansicht

`physical_reset: false` ist ein eigener Admin-Schalter und verlangt
`physical_initialization`. Der eng begrenzte [Resetworkflow](architecture/physical-reset.md)
entsperrt ausdrücklich bestätigte, nicht katalogisierte Pending-Kassetten;
registrierte Archive bleiben geschützt. `POST /api/v1/reset/prepare` und der
Workerauftrag `reset-physical` verwenden denselben Review-/Queuepfad wie die
Initialisierung. Es gibt keine automatische Markerbereinigung.

Die Hardwareansicht gruppiert Medienaktionen und klappt destruktive Bandpflege
separat auf. Sie zeigt den gleichen konkreten Initialisierungssperrgrund wie
die API. Nach Medienwechsel werden Diagnosewerte einer anderen MAM als veraltet
behandelt. Aktuelle TapeAlert-Flags und dauerhaft gespeicherte Historie sind
getrennt; ein alter Hinweis ist kein aktueller Alarm.

Planung und Staging benötigen ein gewähltes katalogisiertes Zielmedium, aber
keine eingelegte Kassette. Das heutige unveränderliche TAR enthält bereits die
Medien-UUID. Vollständig medienunabhängiges Vorstaging ist deshalb noch nicht
implementiert und würde einen eigenen Format-/Bindungsworkflow benötigen.

## Ab 0.6.2: Neuinitialisierung nach abgeschlossener früherer Initialisierung

Das separate default-false Gate `physical_reinitialization` verlangt
`physical_initialization`. Es ersetzt ausschließlich abgeschlossene physische
Initialisierungen, deren Medium nicht mehr im Katalog oder in Bindungen steht.
Die Hardwareansicht nennt alte Medien-ID/Zeit und bietet getrennt lesende
Registrierung oder destruktive Neuinitialisierung an. Ungeklärte Writes werden
nicht freigegeben. Simulatoridentitäten allein blockieren kein reales Medium.
Details: [Workflow und Grenzen](architecture/physical-reinitialization.md).

## Ab 0.7: zuerst Quelle, danach Zielmedien

Die Planung erstellt mit `plan-source` einen gespeicherten, medienfreien
Größenplan und fordert danach Medien an. `bind-plan` benötigt `job_id`,
`source_plan_hash` und `media_ids`. Bei zu wenig Kapazität bleibt der Plan
`WAITING_MEDIA`; es werden keine Inhalte gehasht und keine TARs geschrieben.
Erst bei ausreichender Kapazität entsteht der verbindliche Archivplan.
Der frühere `plan`-Aufruf bleibt kompatibel, prüft Kapazität jetzt ebenfalls
vor dem Hashen. Staging erfolgt weiterhin erst nach Medienzuordnung; dafür
muss kein Band eingelegt sein. [Ablauf und Grenzen](architecture/source-first-planning.md).

Ab 0.7.1 sind explizite `excluded_paths` möglich. Exakte relative Pfade je
Zeile, Ordner einschließlich Unterbaum, keine Muster. Sie gelten unverändert
für Quellenplan, Hashberechnung und Staging und erscheinen im Review. Symlinks
werden niemals automatisch verfolgt oder stillschweigend übersprungen.
