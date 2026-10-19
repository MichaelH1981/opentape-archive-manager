# Konfigurationsreferenz (CLI v0.2)

V1 nutzt explizite CLI-Optionen, keine versteckten Umgebungsvariablen und noch keine TOML-Konfigurationsdatei. `python3 -m otam --help` und Unterbefehl `--help` sind maßgeblich.

| Option | Standard / Bedeutung |
|---|---|
| --db (vor Unterbefehl) | .otam/catalog.sqlite, lokaler versionierter SQLite-Katalog |
| init-sim medium | Neuer Simulatorordner; existierender Ordner wird abgelehnt |
| init-sim --capacity | 800000000000 native Bytes |
| init-sim --class | permanent; alternativ rotation, derzeit ebenfalls ohne Recycling |
| plan --target | 75000000000 Bytes geschätzte TAR-Zielgröße; einzelne größere Dateien nicht teilen |
| --media-id | Erwartete UUID; bei Medienaktionen explizit erforderlich |
| backup --confirm | Exakte Job-ID des zuvor angezeigten Plans |
| stage JOB --staging | Gesamten Plan ohne Bandzugriff lokal vorbereiten |
| backup --staging / --spool | .otam/staging; persistentes lokales Dateisystem außerhalb Quelle/Medium/Katalog; größtes TAR muss hineinpassen |
| backup --prepare-all | Alle TARs vor dem ersten Write fertigstellen; ausreichend Platz für gesamten fehlenden Bestand erforderlich |
| backup --resume | Explizite Wiederaufnahme mit vollständiger erneuter Medien-/Positions-/Receipt-Prüfung; keine Fortsetzung bei partiellem Tail |
| staging-status --staging [--job-id] | Kapazität, freie Bytes, Phasen, Fortschritt und letzte Messwerte |
| staging-benchmark --staging --file | Vorhandene lokale Datei ausschließlich mit O_DIRECT lesen; Linux erforderlich |
| staging-benchmark --seconds | 1800 Sekunden; kürzere Tests qualifizieren niemals für Produktion |
| staging-benchmark --min-rate | 120000000 Bytes/s (120 MB/s dezimal), Zielrate für das Puffermodell mit mindestens 5 % Durchschnittsreserve |
| restore/restore-plan --path | Wiederholbar; Datei oder Verzeichnispräfix; ohne Auswahl alle verifizierten Dateien |
| restore/restore-plan --archive-id | Bestimmte Archivkopie; bei gleichen Pfaden mehrerer Versionen erforderlich |
| restore/restore-plan --target | Explizites Ziel; vorhandene Dateien und Symlink-Pfadkomponenten werden abgelehnt |
| export --format | json (gesamter Katalog) oder csv (gewählte Tabelle) |
| export --table | files, media oder archives; gilt für CSV |

Feste Sicherheitsgrenzen v1: 5 % Kapazitätsreserve; 32 MiB Manifest; 1 MiB I/O-Chunks; keine Kompression, Verschlüsselung, Link-/Spezialdateiarchivierung oder Überschreiboption. Produktionsparameter (Gerätepfad, Blockgröße, mbuffer-RAM, Vorfüllung, Bind-IP) werden erst mit den jeweiligen Phasen konfigurierbar und sind noch nicht aktive Optionen.

Alle temporären Daten können vertrauliche Inhalte enthalten. Quelle nur lesbar einbinden; Arbeitsverzeichnis und Spool dem dedizierten Benutzer zuweisen, z.B. mit umask 077 starten. Datei-Hashes und Inventar liegen als Klartext in Datenbank und Manifest. Keine Schlüssel in Konfigurationsdateien.

Details zu Wiederaufnahme, Cleanup, Lokalitätsprüfung und Leistungsabnahme: [Staging](staging.md). Der reale mbuffer-/nst-Adapter bleibt gesperrt; dessen geplante Konfiguration ist noch nicht aktiv.

Die optionale Web-/Worker-Konfiguration und die eigenständige Katalogrolle sind in [Web-Konfiguration](web-configuration.md) und [Installation/Betrieb](web.md) beschrieben. Die lokalen SQLite-Dateien des Bandservers und Katalogcontainers werden nicht als Netzwerkdatei gemeinsam geöffnet.
