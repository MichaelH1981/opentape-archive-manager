# Modulare Webanwendung und eigenständiger Katalogdienst

Status: Implementierung der Webmodule; echte LTO-Schreibzugriffe bleiben bis zur Testband-Abnahme gesperrt.

## Rollen und Datenhoheit

OTAM Archive Node läuft auf dem Bandserver: lokaler SQLite-Primärkatalog, authentifizierte Web/API, persistente Auftragswarteschlange und separater Worker. Der vorhandene ArchiveService bleibt zuständig für Inventar, Pläne, Staging, Integrität und Restore. Es existiert genau ein schreibender Eigentümer eines Katalogs.

Die Node-lokale Steuerdatenbank enthält ab Schema 2 Benutzer mit Rolle, Sprache und einem für künftige MFA-Migrationen reservierten Status. Sitzungen referenzieren Benutzer-IDs. Katalogreplikation umfasst diese Steuerdatenbank nicht; Archive Node und optionale Catalog Nodes verwalten ihre Zugänge unabhängig. Die API prüft Rechte serverseitig: Leser erhalten nur Lesezugriff, Operatoren dürfen Archivaufträge ausführen, Administratoren verwalten Konten, Ressourcen und Bandwartung. Die Oberfläche blendet unzulässige Aktionen zusätzlich aus. Alte anonyme Sitzungen werden bei der Migration verworfen. 2FA ist vorbereitet, aber noch nicht implementiert.

Ein optionaler OTAM Catalog Node läuft unabhängig auf einem geeigneten Linux-System, einer VM oder einem Container: eigene Web/API für Dateisuche, Medien, Archive, Jobs und Protokolle. Er benötigt weder erreichbaren Bandserver noch dessen Dateisysteme oder ein Bandlaufwerk. Er veröffentlicht ausschließlich validierte Replikate seines fest konfigurierten Herausgebers. Keine Archivierungsbefehle oder Rückschreibungen vom Replikat zum Primärkatalog; damit keine Mehrschreiber-Konflikte.

Die Module catalog, archive und replication besitzen getrennte Router/Dienste und ein Capability-Manifest. Der Catalog Node lädt keine Archivierungsrouten. Dieselbe statische, lokal ausgelieferte Oberfläche zeigt die verfügbaren Fähigkeiten; der Server erzwingt die Grenzen zusätzlich. Das ist ein eingebautes Modulmodell, keine Möglichkeit zum Ausführen beliebiger fremder Plugin-Skripte.

Ein optionales Snapshot-Verzeichnis ist Sicherungsziel für abgeschlossene Katalog-Snapshots; es kann lokal oder auf einer eingehängten Netzwerkfreigabe liegen. Keine bestimmte Infrastruktur ist vorausgesetzt. Die laufenden SQLite-Datenbanken liegen jeweils auf lokalem persistentem Speicher des Bandservers bzw. Containers, niemals als gemeinsam geöffnete WAL-Datei auf NFS/SMB. Die SQLite-Dokumentation beschreibt [Netzwerkdateisystem-Risiken](https://sqlite.org/howtocorrupt.html) und die [Online Backup API](https://sqlite.org/backup.html). Die Trennung von Steuerung, Katalog und Speicher orientiert sich an den [Bareos-Komponenten](https://www.bareos.com/bareos-system-components/); OTAM verwendet keine Bareos-Protokolle oder -Quellen.

## Transport und Veröffentlichung

Synchronisation ist eine gerichtete Veröffentlichung vollständiger, konsistenter SQLite-Snapshots über die Online Backup API. V1 vermeidet fragile JSON-Zeilen-Merges und verwendet vollständige Snapshots; große Kataloge erfordern später gemessene inkrementelle Replikation. Alle Datei- und Archivzustände bleiben erhalten, einschließlich INCOMPLETE und SUSPECT. Die API filtert Zustände nicht stillschweigend als erfolgreich.

Jeder Snapshot besitzt Herausgeber-ID, persistente monoton steigende Sequenz, Formatversion, Erstellungszeit, Größe, SHA-256 und HMAC-SHA-256 über diese Metadaten. Ein separat geschützter Peer-Schlüssel authentifiziert beide Seiten. HTTPS ist der Standard; HTTP ist ausschließlich über explizite Konfiguration für einen vertrauenswürdigen lokalen/WireGuard-Transport zulässig. Kein automatisches Folgen von Redirects. Nur authentifizierte Administratoren mit CSRF-Token dürfen Ziele über die Zielverwaltung konfigurieren; Archivierungsbefehle akzeptieren weiterhin keine frei wählbaren Transportadressen.

Empfang in eigene temporäre Datei mit Größenlimit und Platzprüfung, vollständige Hash-/Signatur-/Schema-/Integritätsprüfung, danach atomare Veröffentlichung. Ein fehlgeschlagener Transfer ersetzt nie den letzten gültigen Stand. Veraltete Sequenzen und andere Herausgeber werden abgelehnt; identische Wiederholung ist idempotent. Der aktive Snapshot und der zuletzt erfolgreiche Zeitpunkt werden dauerhaft erfasst. Beim Quellverlust bleibt das Replikat lesbar. Alte veröffentlichte Snapshots werden nicht automatisch gelöscht. Ein wiederhergestellter Primärserver mit zurückgesetztem Sequenzstand benötigt eine bewusste Replikations-Recovery; kein stilles Zurückrollen des Empfängers.

Der Worker bietet manuelle und intervallgesteuerte Synchronisation. Bei Nichterreichbarkeit bleibt der lokale Archivkatalog maßgeblich, der Fehler wird gespeichert und die nächste Intervallausführung versucht erneut. Ein unterbrochener Auftrag wird nie blind als Archivierung neu ausgeführt.

## Web und Worker

FastAPI/Uvicorn ist die optionale Web-Laufzeit. Der bisherige Python-Kern bleibt ohne zusätzliche Laufzeitabhängigkeiten bedienbar. Kein CDN, keine externen Schriften, keine Telemetrie. Vanilla JavaScript und CSS erlauben eine schlanke Oberfläche ohne Frontend-Builddienst.

Webprozess und Worker sind getrennte Dienste. HTTP-Anfragen schreiben überprüfte Befehle in eine lokale SQLite-Steuerdatenbank. Ein exklusiver Worker-Lock verhindert parallele Ausführung auf demselben Node; zusätzlich gelten weiterhin die Geräte-/I/O-Sperren des Kerns. Queue- und Kernzustände werden getrennt angezeigt. Nach Workerabbruch wird RUNNING als INTERRUPTED markiert; kein automatisches Wiederholen von Schreibbefehlen. Geplante Queue-Einträge bleiben erhalten. Staging- und Restore-Pfade sind fest konfiguriert, Quellen und Simulatormedien werden über erlaubte Ressourcen-IDs ausgewählt.

Authentifizierung über passwortgeschützte Sessions (PBKDF2-SHA-256, HttpOnly, SameSite=Strict, feste Ablaufzeit), CSRF-Token und Origin-Prüfung für Mutationen. Host-Allowlist gegen DNS-Rebinding; Standardbindung 127.0.0.1. Kein Passwort oder Peer-Schlüssel in API-Antworten, Logs oder Git. Gesonderter Peer-Bearer/HMAC-Zugang nur zur Synchronisation. Kein Login-Passwort im Browser-Storage. Keine Hardware-Schreibfreigabe durch Webbestätigung ableiten.

## Abnahmegrenzen

Simulatorjobs können vollständig geplant, vorbereitet, bestätigt, archiviert, verifiziert und wiederhergestellt werden. Physische LTO-Aktionen werden als nicht verfügbar angezeigt und bleiben serverseitig blockiert. System-Snapshots, Verschlüsselung, automatische Medienrotation und echte physische Mehrbandwechsel werden nicht als vorhandene Funktionen dargestellt. Mehrbandplanung und bestätigter Medienwechsel sind im Simulator implementiert.

Softwareabnahme: authentifizierter HTTP-Zyklus, CSRF/Host/Origin, Worker-Neustart, Pfadgrenzen, Katalogfilter/Pagination/Kopien, eigenständige Suche nach Primärserver-Ausfall, korruptes/unterbrochenes Snapshot-Upload, Replay, falsche Herausgeber, NAS-Export, Desktop-/Mobilbrowser. Hardwareabnahme und reale Proxmox-/NAS-Installation bleiben eigenständige Schritte.

## Explizite erneute Staging-Prüfung

Eine nachträgliche ctime-Änderung eines vorbereiteten TARs wird vor Schreiben weiterhin abgelehnt. Auf macOS wurde in der Vorschau eine solche Änderung bei unverändertem Hash und vorhandenem `com.apple.provenance` beobachtet; der Verursacher ist nicht abschließend bestimmt. Kein automatischer Metadaten-Workaround. Der Betreiber kann vor jedem Bandversuch ausdrücklich eine erneute Staging-Prüfung bestätigen. Sie erhält den ursprünglichen Hash, verlangt denselben Datenträger/Inode, dieselbe Größe/mtime und schreibgeschützten Modus und prüft TAR und Dateimanifest vollständig. Erst dann wird der neue Fingerprint mit Audit-Ereignis gespeichert. Geänderter Inhalt, Dateiaustausch und bereits versuchte Schreibvorgänge werden nicht auf diesem Weg freigegeben.

## Lokaler Pflichtkatalog, optionale Veröffentlichungsziele

Der lokale SQLite-Primärkatalog ist untrennbarer Bestandteil des Archive Node. Die Zielverwaltung kann ihn weder deaktivieren noch durch ein entferntes Ziel ersetzen. Eine leere Zielliste ist ein vollständig unterstützter Betriebszustand. Es gibt keine Abhängigkeit von Proxmox, NAS, Hostnamen oder konkreten Netzwerkadressen.

`targets.py` kapselt das Zielmodell mit den Typen `catalog` (eigenständige Suchoberfläche über den Snapshot-Empfangsdienst) und `directory` (abgeschlossene SQLite-/Manifest-Dateien). Authentifizierte PUT/DELETE-Routen verwalten mehrere Ziele dauerhaft in der lokalen Steuerdatenbank. Jedes Ziel besitzt UUID, Bezeichnung, Adresse/Pfad, Aktivierung, Intervall, eigenen HMAC-Schlüssel, Konfigurationsrevision und persistenten Einzelstatus. Geheimnisse werden ausschließlich in der privaten Steuerdatenbank gespeichert (State-Verzeichnis 0700, Datenbank 0600) und nie über GET zurückgegeben. Diese Steuerdatenbank gehört in die geschützte Installationssicherung; sie ist ausdrücklich nicht Teil veröffentlichter Katalog-Snapshots.

Bestehende `peer_url`-/`nas_backup`-Felder werden als Legacy-Ziele angezeigt. Die erste Änderung der Zielliste übernimmt diese in die neue Verwaltung. Danach ist ausschließlich diese Liste maßgeblich; entfernte oder deaktivierte Ziele werden beim Neustart nicht aus den Legacy-Feldern wieder aktiviert. Das Katalogschema bleibt Version 2, die erweiterbare Steuerdatenbank verwendet ihre vorhandene Settings-Tabelle ohne Änderung des Dateischemas.

Der Worker bearbeitet Ziele unabhängig. Fehler eines Ziels verhindern weder weitere Ziele noch lokale Archivierung oder Suche. Ein Sammelauftrag mit Fehlern erhält FAILED und behält seine erfolgreichen Einzelresultate. Unveränderte Kataloge werden anhand des letzten bestätigten Hashes pro Ziel und Konfigurationsrevision nicht erneut übertragen; UNCHANGED ist kein Erreichbarkeitsnachweis. Geänderte Ziele werden erneut beliefert, fehlgeschlagene Ziele erneut versucht. Ein Hintergrundlauf berücksichtigt pro Ziel dessen Intervall; manuelle Synchronisation prüft alle aktiven Ziele. Übertragungen bleiben bewusst sequenziell, damit keine unnötige parallele I/O-Last auf dem kleinen Archivserver entsteht. Ein langsames Ziel kann nachfolgende Ziele bis zu seinem Transport-Timeout verzögern; es besteht keine verteilte Transaktion.

Verzeichnisziele dürfen nicht mit Quellen oder internen Node-Daten überlappen. Diese Grenze wird bei Konfiguration und vor Veröffentlichung anhand aufgelöster Pfade geprüft. Die Registrierung schreibt noch nicht in das Ziel. Über die separate Aktion „Zielmarker“ und Bestätigung der Node-ID kann ein Betreiber ein vorhandenes Verzeichnis explizit freigeben; bestehende Marker werden nie ersetzt und Mountpunkte nie automatisch angelegt. Mount, Rechte und systemd-Sandbox bleiben Administrationsaufgaben. Echte Band-Schreibfreigaben sind hiervon unabhängig.
