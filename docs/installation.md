# Installation und Aktualisierung

OTAM benötigt Python >=3.11 und SQLite. Linux ist die Zielplattform für
physische Bandarchive; der Simulator ist zusätzlich unter macOS testbar.
Der Betrieb benötigt weder Internetzugriff noch externe Datenbankdienste.
Der aktuelle Freigabestand steht in [production-readiness.md](production-readiness.md).

## Software und Dienste

```bash
python3 -m venv /opt/otam/venv
/opt/otam/venv/bin/python -m pip install -r packaging/requirements-web.lock
/opt/otam/venv/bin/python -m pip install --no-deps --no-build-isolation .
python3 -m otam --help
python3 -m unittest discover -s tests
```

Für Offlineinstallation vorher Wheels einschließlich des festgehaltenen
Build-Backends bereitstellen und mit `--no-index --find-links` installieren.
Webinitialisierung, Benutzer und optionale Katalogziele beschreibt
[web.md](web.md); Konfiguration und Gates stehen in
[web-configuration.md](web-configuration.md). Kein Standardpasswort.

Die Vorlagen in `packaging/systemd/` betreiben Webdienst und Worker separat
als unprivilegierten Benutzer `otam`. Schreibrechte nur für den eigenen
Zustand sowie ausdrücklich konfigurierte Staging-/Restore-/Backup-Verzeichnisse.
Quellen erhalten Leserechte. Webzugriff standardmäßig localhost; eine interne
Adresse muss ausdrücklich konfiguriert werden. Fernzugriff über VPN.

## Physische Bandgeräte

Benötigt werden etablierte Distributionspakete: `mt-st`, `mbuffer`, `sg3-utils`
und Werkzeuge zur lesenden Laufwerkserkennung. Keine eigenen Treiber.
Udev-Regeln und der optionale Worker-Drop-in unter `packaging/` gewähren
Gerätezugriff ausschließlich über die Gruppe `otam-tape`. Der Webdienst
behält `PrivateDevices=true`; keine root-Dauerdienste.

Vor Aktivierung: passendes geprüftes Laufwerksprofil, lokale
Staging-Qualifikation, genügend freier RAM/Plattenplatz, frische Erkennung,
Medienbindung und gespeicherte Transferwerte. `physical_archiving`,
`physical_initialization` und `physical_multivolume` sind standardmäßig false
und getrennt freizugeben. Neue oder fremde Hardware wird durch das Aktivieren
eines Flags nicht qualifiziert. Initialisierung ist destruktiv und erfordert
den separaten Review mit konkreter Drive-/MAM-Identität.

## Sicher aktualisieren

1. Sicherstellen, dass keine Archivierung, Verifikation oder Wiederherstellung läuft.
2. Worker kontrolliert stoppen; einen laufenden Bandvorgang niemals per Zeitlimit töten.
3. Katalog und Control mit der SQLite-Backup-API sichern, dazu Konfiguration, Schlüssel
   und dauerhafte Pending-Journale sichern. Laufende WAL-Dateien nicht isoliert kopieren.
4. Neue Version getrennt bereitstellen und mit isoliertem lokalem Test-TMPDIR testen.
5. Erst nach bestandenen Prüfungen installieren; Konfiguration und Daten erhalten.
6. Dienste starten, Healthcheck, Anmeldung, Rollen-/CSRF-Schutz, Suche, Einstellungen,
   Worker, Geräteberechtigungen und optionale Katalogsynchronisation prüfen.

Eine Paketaktualisierung löscht keine Medien und bereinigt keine Pending-Marker.
Abgebrochene Writes bleiben gesperrt, bis ihre Unsicherheit ausdrücklich
untersucht wurde. Katalogbereinigung ersetzt weder Bandlöschen noch
Medieninitialisierung. Historische Abnahmeberichte bleiben unabhängig erhalten.

Venvs nicht verschieben: Launcher enthalten absolute Interpreterpfade. Bei
Aktualisierungen ausdrücklich `python -m pip` des Zielinterpreters verwenden
und danach Version sowie Importpfad aus genau dieser Umgebung kontrollieren.

Beim Installieren als root muss die Programmdatei-Umask 0022 gelten, z. B.
`(umask 022; /opt/otam/venv/bin/python -m pip install ...)`. Eine private
Backup-/Konfigurations-Umask 0077 darf nicht ungeprüft auf die Paketinstallation
übertragen werden. Vor Dienststart Import und CLI ausdrücklich als Dienstkonto
prüfen (`sudo -u otam /opt/otam/venv/bin/python -I -c 'import otam.cli'`).
Programmverzeichnisse 0755/Programmdateien 0644; private Konfiguration,
Steuerkatalog, Schlüssel und Journale behalten ihre restriktiven Rechte.
