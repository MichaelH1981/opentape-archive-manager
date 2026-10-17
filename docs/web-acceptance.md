# Abnahmeprotokoll Web und eigenständiger Katalog – 0.3.0

Datum: 17.10.2026. Ausschließlich synthetische Daten und persistente Simulatormedien; keine physischen Bandzugriffe oder produktiven Quelldaten verändert.

| Prüfung | Ergebnis |
|---|---|
| Vollständige Suite, Linux/Debian/Python 3.13 | 70 Tests bestanden; isolierte temporäre Umgebung anschließend entfernt |
| Vollständige Suite, macOS/Python 3.13 | 69 bestanden, ein Linux-O_DIRECT-Test übersprungen |
| HTTP-Planung → Staging → bestätigtes Schreiben → Rücklesen → Restore | Bestanden, einschließlich Inhaltsvergleich und Schutz vorhandener Dateien |
| Authentifizierung, Host/Origin/CSRF, Ablauf/Logout, Fehlversuche | Bestanden |
| Ungültige Ressourcen-IDs und übergroße Filter | Kontrolliert als Clientfehler abgelehnt |
| Queue-Neustart, Idempotency, exklusiver Worker | Bestanden; unterbrochene Schreibaufträge nicht automatisch erneut ausgeführt |
| Verändertes READY-TAR | Vor Schreiben verweigert; ausdrückliche Vollprüfung akzeptiert nur unveränderte Inhalte/Identität und geeigneten Zustand |
| Replikation über zwei laufende lokale HTTP-Dienste | Erfolgreich veröffentlicht, Version und Inhalt bestätigt |
| Archive-Webdienst und Worker tatsächlich gestoppt | Standalone-Webkatalog weiterhin durchsuchbar; zwei Kopien derselben Datei gefunden |
| Beschädigte/unterbrochene/veraltete/fremde Snapshots | Kein Ersatz des letzten gültigen Standes |
| NAS-Export | Mit synthetischem Sicherungsziel/Marker getestet; kein echter NAS-Mount verändert |
| Browser, Desktop 1440 Pixel | Dashboard, Planungs-/Staging-/Bestätigungsdialog, Archivierung, Dateiauswahl und Restore bedient |
| Browser, Mobilbreite 390 Pixel | Übersicht, sichtbarer Katalogstand und Navigation geprüft; keine horizontale Ausdehnung der gesamten Seite |
| Browser-JavaScript | Keine verbliebenen Konsolenfehler im geprüften aktuellen Stand |
| Python-Wheel | Erfolgreich gebaut; alle zehn lokalen Frontend-Assets enthalten |

Die unabhängige Suche wurde nicht durch einen Mock des Primärservers simuliert: Web- und Workerprozess des Archive Node waren beendet. Der Catalog Node lief mit eigenem Steuerdatenverzeichnis und veröffentlichter SQLite-Snapshot-Datei weiter. Danach wurde die lokale Vorschau wieder gestartet.

Screenshots verwenden ausschließlich synthetische Beispieldateien: [Dashboard](images/otam-dashboard.jpg), [Standalone-Katalog](images/catalog-standalone.jpg), [Mobilansicht](images/otam-mobile.jpg). Die gezeigte Speicherkapazität ist die reale Dateisystembelegung des Entwicklungsrechners, keine zugesicherte Staging-Kapazität des Archivservers. Angezeigter Simulator-Durchsatz ist keine gemessene Bandrate.

## Ausstehende Betriebsabnahmen

Echtes LTO-Schreiben/Filemarks/EOM, produktive Archive, Proxmox-LXC-Installation, tatsächlicher NAS-Mount und Restore aus dessen Backup, OCI-Imagebau/Containerstart (keine Container-Engine verfügbar), tatsächliches iPhone/iOS Safari sowie Langzeittest und Lastprüfung großer Kataloge sind nicht abgenommen. Service-/Containerdateien sind vorbereitete Vorlagen. Kein Anspruch auf abgeschlossene produktive LTO-Freigabe oder vollständige Umsetzung aller späteren Lastenheftphasen.

Die Sicherheits- und Architekturentscheidungen stehen in [modular-web](architecture/modular-web.md); Installation und Wiederaufnahme in [Webbetrieb](web.md).

## Ergänzung: frei konfigurierbare optionale Ziele

75 Tests auf dem Linux-Bandserver bestanden; macOS: 74 bestanden, ein Linux-spezifischer Test übersprungen. Keine Änderung an produktiven Daten oder physischen Bandmedien.

Zusätzlich geprüft: leerer Zielbestand mit verfügbarem lokalem Katalog, persistente Zielverwaltung und Deaktivierung, Schutz vor erneutem Import entfernter Legacy-Ziele, unabhängige Fehlerbehandlung bei mehreren Zielen, gezielte Wiederholung fehlgeschlagener Übertragungen, unterschiedliche HMAC-Schlüssel je Empfänger, Einhaltung zielbezogener Intervalle, Schlüsselredaktion und private Steuerdaten, CSRF und Validierung, explizite Zielmarker sowie Ablehnung eines nachträglich in Quelldaten umgeleiteten Verzeichnisziels. Synchronisationsaufträge mit Einzelproblemen melden FAILED und bewahren erfolgreiche Resultate.

Im Browser wurde ein vorhandenes lokales Simulator-Ziel bearbeitet, ohne erneute Schlüsseleingabe gespeichert und die Veröffentlichung an den eigenständigen Vorschaukatalog ausgelöst. Die Zielverwaltung benötigt keinen Dienstneustart. Der Konfigurationsdialog und die Zielübersicht wurden zusätzlich bei 390 Pixel Breite ohne horizontale Seitenüberbreite geprüft; keine JavaScript-Konsolenfehler. Die Desktopansicht ist unter [Optionale Ziele](images/otam-optional-targets.jpg) dokumentiert. Proxmox-/NAS-Deployment und physische Bandabnahme bleiben separat offen.
