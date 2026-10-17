# Modulare Webanwendung und eigenständiger Katalogdienst

Status: Implementierung der Webmodule; echte LTO-Schreibzugriffe bleiben bis zur Testband-Abnahme gesperrt.

## Rollen und Datenhoheit

OTAM Archive Node läuft auf dem Bandserver: lokaler SQLite-Primärkatalog, authentifizierte Web/API, persistente Auftragswarteschlange und separater Worker. Der vorhandene ArchiveService bleibt zuständig für Inventar, Pläne, Staging, Integrität und Restore. Es existiert genau ein schreibender Eigentümer eines Katalogs.

OTAM Catalog Node läuft unabhängig in einem Proxmox-Container: eigene Web/API für Dateisuche, Medien, Archive, Jobs und Protokolle. Er benötigt weder erreichbaren Bandserver noch dessen Dateisysteme oder ein Bandlaufwerk. Er veröffentlicht ausschließlich validierte Replikate seines fest konfigurierten Herausgebers. Keine Archivierungsbefehle oder Rückschreibungen vom Replikat zum Primärkatalog; damit keine Mehrschreiber-Konflikte.

Die Module catalog, archive und replication besitzen getrennte Router/Dienste und ein Capability-Manifest. Der Catalog Node lädt keine Archivierungsrouten. Dieselbe statische, lokal ausgelieferte Oberfläche zeigt die verfügbaren Fähigkeiten; der Server erzwingt die Grenzen zusätzlich. Das ist ein eingebautes Modulmodell, keine Möglichkeit zum Ausführen beliebiger fremder Plugin-Skripte.

Das NAS ist Sicherungsziel für abgeschlossene Katalog-Snapshots. Die laufenden SQLite-Datenbanken liegen jeweils auf lokalem persistentem Speicher des Bandservers bzw. Containers, niemals als gemeinsam geöffnete WAL-Datei auf NFS/SMB. Die SQLite-Dokumentation beschreibt [Netzwerkdateisystem-Risiken](https://sqlite.org/howtocorrupt.html) und die [Online Backup API](https://sqlite.org/backup.html). Die Trennung von Steuerung, Katalog und Speicher orientiert sich an den [Bareos-Komponenten](https://www.bareos.com/bareos-system-components/); OTAM verwendet keine Bareos-Protokolle oder -Quellen.

## Transport und Veröffentlichung

Synchronisation ist eine gerichtete Veröffentlichung vollständiger, konsistenter SQLite-Snapshots über die Online Backup API. V1 vermeidet fragile JSON-Zeilen-Merges und verwendet vollständige Snapshots; große Kataloge erfordern später gemessene inkrementelle Replikation. Alle Datei- und Archivzustände bleiben erhalten, einschließlich INCOMPLETE und SUSPECT. Die API filtert Zustände nicht stillschweigend als erfolgreich.

Jeder Snapshot besitzt Herausgeber-ID, persistente monoton steigende Sequenz, Formatversion, Erstellungszeit, Größe, SHA-256 und HMAC-SHA-256 über diese Metadaten. Ein separat geschützter Peer-Schlüssel authentifiziert beide Seiten. HTTPS ist der Standard; HTTP ist ausschließlich über explizite Konfiguration für einen vertrauenswürdigen lokalen/WireGuard-Transport zulässig. Kein automatisches Folgen von Redirects oder konfigurierbares Ziel aus Browseranfragen.

Empfang in eigene temporäre Datei mit Größenlimit und Platzprüfung, vollständige Hash-/Signatur-/Schema-/Integritätsprüfung, danach atomare Veröffentlichung. Ein fehlgeschlagener Transfer ersetzt nie den letzten gültigen Stand. Veraltete Sequenzen und andere Herausgeber werden abgelehnt; identische Wiederholung ist idempotent. Der aktive Snapshot und der zuletzt erfolgreiche Zeitpunkt werden dauerhaft erfasst. Beim Quellverlust bleibt das Replikat lesbar. Alte veröffentlichte Snapshots werden nicht automatisch gelöscht. Ein wiederhergestellter Primärserver mit zurückgesetztem Sequenzstand benötigt eine bewusste Replikations-Recovery; kein stilles Zurückrollen des Empfängers.

Der Worker bietet manuelle und intervallgesteuerte Synchronisation. Bei Nichterreichbarkeit bleibt der lokale Archivkatalog maßgeblich, der Fehler wird gespeichert und die nächste Intervallausführung versucht erneut. Ein unterbrochener Auftrag wird nie blind als Archivierung neu ausgeführt.

## Web und Worker

FastAPI/Uvicorn ist die optionale Web-Laufzeit. Der bisherige Python-Kern bleibt ohne zusätzliche Laufzeitabhängigkeiten bedienbar. Kein CDN, keine externen Schriften, keine Telemetrie. Vanilla JavaScript und CSS erlauben eine schlanke Oberfläche ohne Frontend-Builddienst.

Webprozess und Worker sind getrennte Dienste. HTTP-Anfragen schreiben überprüfte Befehle in eine lokale SQLite-Steuerdatenbank. Ein exklusiver Worker-Lock verhindert parallele Ausführung auf demselben Node; zusätzlich gelten weiterhin die Geräte-/I/O-Sperren des Kerns. Queue- und Kernzustände werden getrennt angezeigt. Nach Workerabbruch wird RUNNING als INTERRUPTED markiert; kein automatisches Wiederholen von Schreibbefehlen. Geplante Queue-Einträge bleiben erhalten. Staging- und Restore-Pfade sind fest konfiguriert, Quellen und Simulatormedien werden über erlaubte Ressourcen-IDs ausgewählt.

Authentifizierung über passwortgeschützte Sessions (PBKDF2-SHA-256, HttpOnly, SameSite=Strict, feste Ablaufzeit), CSRF-Token und Origin-Prüfung für Mutationen. Host-Allowlist gegen DNS-Rebinding; Standardbindung 127.0.0.1. Kein Passwort oder Peer-Schlüssel in API-Antworten, Logs oder Git. Gesonderter Peer-Bearer/HMAC-Zugang nur zur Synchronisation. Kein Login-Passwort im Browser-Storage. Keine Hardware-Schreibfreigabe durch Webbestätigung ableiten.

## Abnahmegrenzen

Simulatorjobs können vollständig geplant, vorbereitet, bestätigt, archiviert, verifiziert und wiederhergestellt werden. Physische LTO-Aktionen werden als nicht verfügbar angezeigt und bleiben serverseitig blockiert. System-Snapshots, Verschlüsselung, automatische Medienrotation und echte Mehrbandwechsel werden nicht als vorhandene Funktionen dargestellt.

Softwareabnahme: authentifizierter HTTP-Zyklus, CSRF/Host/Origin, Worker-Neustart, Pfadgrenzen, Katalogfilter/Pagination/Kopien, eigenständige Suche nach Primärserver-Ausfall, korruptes/unterbrochenes Snapshot-Upload, Replay, falsche Herausgeber, NAS-Export, Desktop-/Mobilbrowser. Hardwareabnahme und reale Proxmox-/NAS-Installation bleiben eigenständige Schritte.

## Explizite erneute Staging-Prüfung

Eine nachträgliche ctime-Änderung eines vorbereiteten TARs wird vor Schreiben weiterhin abgelehnt. Auf macOS wurde in der Vorschau eine solche Änderung bei unverändertem Hash und vorhandenem `com.apple.provenance` beobachtet; der Verursacher ist nicht abschließend bestimmt. Kein automatischer Metadaten-Workaround. Der Betreiber kann vor jedem Bandversuch ausdrücklich eine erneute Staging-Prüfung bestätigen. Sie erhält den ursprünglichen Hash, verlangt denselben Datenträger/Inode, dieselbe Größe/mtime und schreibgeschützten Modus und prüft TAR und Dateimanifest vollständig. Erst dann wird der neue Fingerprint mit Audit-Ereignis gespeichert. Geänderter Inhalt, Dateiaustausch und bereits versuchte Schreibvorgänge werden nicht auf diesem Weg freigegeben.
