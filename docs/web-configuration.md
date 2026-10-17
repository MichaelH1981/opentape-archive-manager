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

Befehlsarten: `create-medium`, `plan`, `stage`, `backup`, `verify`, `restore`, `recover`, `rebuild`, `sync`. HTTP 202 bedeutet angenommen, nicht abgeschlossen. Über `/commands` und den referenzierten Kernjob das Ergebnis prüfen. `backup` verlangt Job-ID sowohl in `job_id` als auch `confirm` und den geprüften `plan_hash`. `resume` ist ein ausdrücklicher boolescher Parameter. `stage` mit `revalidate_ready=true` verlangt ebenfalls `confirm=job_id`; es ist kein Weg zur Akzeptanz geänderter TAR-Inhalte. Ein identischer Idempotency-Key gibt denselben Auftrag zurück; andere Nutzdaten mit demselben Key werden abgelehnt.

Dateisuchgrößen sind Bytes, `after`/`before` Änderungszeitpunkte in Unix-Nanosekunden. Pagination maximal 200 Treffer pro API-Seite. CSV-Export entschärft Tabellenformeln; JSON bewahrt die ursprünglichen Dateinamen.

## Replikationszustände

Der Herausgeber zählt Snapshots persistent, auch wenn eine Übertragung fehlschlägt; Sequenzlücken sind zulässig. Gleiche Sequenz und gleicher Inhalt: idempotent. Gleiche Sequenz mit anderem Inhalt oder eine kleinere Sequenz: verweigert. Neue Snapshots werden zunächst vollständig in eine eigene `.partial`-Datei geschrieben und vor Veröffentlichung geprüft. Frühere aktive Snapshot-Dateien bleiben erhalten. Nur die kleine aktive Referenz wird transaktional umgestellt; ein Dateipublikations-Crash hinterlässt höchstens ein noch nicht aktives Artefakt, das eine identische Wiederholung erkennen kann.

NAS-Export und Peer-Veröffentlichung sind zwei getrennte Ziele ohne verteilte Transaktion. Der NAS-Export erfolgt zuerst. Ein erfolgreicher NAS-Export und danach ausgefallener Peer ist als fehlgeschlagene Synchronisation sichtbar; das NAS-Backup bleibt vorhanden. Ein weiterer Versuch verwendet eine neue Sequenz und überschreibt nichts. Geheimnisse nicht in die Übertragungsprotokolle schreiben.
