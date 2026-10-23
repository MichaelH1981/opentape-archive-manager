# Debian 13 installieren

Diese Anleitung gilt für das Debian-Paket ab OTAM 0.8.6. Eine bestehende manuelle
`/opt/otam`-Installation wird absichtlich nicht automatisch ersetzt. Dafür gilt
weiterhin der gesicherte Updateablauf in [installation.md](installation.md).

## Voraussetzungen

- Debian 13 (Trixie), systemd, Python 3.13 aus Debian. Das Paket selbst ist `all`;
  native Python-Abhängigkeiten stammen passend zur Rechnerarchitektur aus APT.
- Lokaler persistenter Speicher für Katalog und Control; keine SQLite auf NFS.
- Für echte Bandarchive separat eingebundener, qualifizierter lokaler
  Staging-Speicher und ein von OTAM unterstütztes, tatsächlich geprüftes Laufwerk.
- Leserechte des Dienstkontos auf Quellen. NFS erlaubt zunächst den Client;
  Datei-UIDs, Gruppen/ACLs bzw. die NAS-Benutzerzuordnung gelten zusätzlich.

Der Webdienst bindet anfangs ausschließlich `127.0.0.1:8765`. Physische
Wartung/Archivierung/Initialisierung/Mehrbandbetrieb sind standardmäßig gesperrt.
Das Paket erstellt keine Testarchive und initialisiert kein Band.

## Paket installieren

Passendes `.deb` und `SHA256SUMS` aus derselben GitHub-Veröffentlichung laden.
Die Download-URL enthält die konkrete Versionsnummer. Prüfsumme vergleichen:

```sh
sha256sum opentape-archive-manager_0.8.6_all.deb
# Mit der entsprechenden Zeile in SHA256SUMS vergleichen.
sudo apt update
sudo apt install ./opentape-archive-manager_0.8.6_all.deb
sudo systemctl status otam-web otam-worker
```

APT installiert die Debian-Pakete für FastAPI, Uvicorn und HTTPX. Es gibt keinen
versteckten pip-Download im Installationsskript und keine mitgelieferten fremden
Binärtreiber. Das Debian-Paket verwendet `/usr/bin/otam`; die Quellinstallation
mit Venv verwendet weiterhin ihren eigenen Interpreter.

## Erstes Administratorkonto anlegen

1. Auf dem Server den einmaligen Einrichtungsschlüssel anzeigen:

   ```sh
   sudo cat /var/lib/otam/state/first-start.token
   ```

2. Lokal `http://127.0.0.1:8765` öffnen. Für einen entfernten Server einen SSH-Tunnel
   benutzen, beispielsweise:

   ```sh
   ssh -N -L 8765:127.0.0.1:8765 benutzer@bandserver
   ```

3. In **OTAM erstmals einrichten** den Schlüssel, einen Benutzernamen und das
   gewünschte Passwort zweimal eingeben. Mindestens zwölf Zeichen; ein langes,
   eigenes Passwort verwenden. Es gibt kein Standardpasswort.
4. Anschließend mit diesem Konto anmelden. Der Schlüssel wird nach erfolgreicher
   Einrichtung entfernt und die Einrichtung dauerhaft geschlossen. Ein Neustart
   oder erneutes Öffnen der Seite erzeugt keinen neuen Administrator.

Einrichtungsschlüssel nicht in URLs, Screenshots, Issues oder öffentliches Git
kopieren. Wer ihn vor der Einrichtung besitzt und den Dienst erreicht, kann das
erste Administratorkonto anlegen. Nach dem Abschluss ist er nicht erneut nutzbar.
Bestehende Installationen werden nicht in den Einrichtungsmodus versetzt.

## Verzeichnisse und physische Geräte freigeben

Zuerst geeigneten Staging-Datenträger korrekt mounten; anschließend die eigenen
OTAM-Verzeichnisse auf diesem Datenträger anlegen. Beispiele sind
`/srv/otam/staging` und `/srv/otam/restores`. Nur diese beschreibbaren Verzeichnisse
gehören `otam`; niemals die produktiven Quellen pauschal umhängen oder umchownen.

In `/etc/otam/node.json` mit `sudoedit` die Werte `staging`, `restore_root` und die
administrativ freigegebenen `directory_roots` setzen. UUIDs, Passwortfeld und
andere generierte Werte erhalten. Beispiel für zusätzliche Picker-Wurzeln:

```json
"directory_roots": ["/mnt", "/srv/otam"]
```

Für die externen Schreibziele einen Worker-Drop-in anlegen:

```sh
sudo systemctl edit otam-worker
```

```ini
[Service]
ReadWritePaths=/srv/otam/staging /srv/otam/restores
```

Danach im Leerlauf `sudo systemctl daemon-reload` und
`sudo systemctl restart otam-web otam-worker`. Die Dienste arbeiten als `otam`;
Leserechte als dieses Konto prüfen, nicht nur als eigener SSH-Benutzer.

Für physische Geräte `sudo apt install mt-st mbuffer sg3-utils lsscsi`.
Die Beispiele unter `/usr/share/doc/opentape-archive-manager/examples/` zeigen
Udev-Regeln und Worker-Gruppenzugriff. Diese werden nicht automatisch aktiviert.
Zuerst die konkrete Hardware und das Geschwindigkeitsprofil prüfen, Udev/Gruppe
administrativ einrichten, lokale Staging-Qualifikation durchführen und erst dann
die nötigen `physical_*`-Gates in der Konfiguration freigeben. Der Webdienst
benötigt keinen direkten Schreibzugriff auf Bandgeräte.

Ein funktionierender Simulator bestätigt den Ablauf, nicht die Eignung eines
beliebigen Bandlaufwerks. Bisherige physische Abnahmen betreffen das dokumentierte
IBM-LTO-4-Profil. Keine automatische Hardwarefreigabe für andere Modelle.

## Aktualisieren und entfernen

Vor dem Update aktive Jobs vollständig abschließen, Katalog/Control mit SQLite-
Backup-API sowie Konfiguration und Sicherheitsjournale sichern. Bei RUNNING,
PLANNING, eingereihten Aufträgen oder ungeklärten physischen Journaleinträgen
verweigert der Paketvorlauf ein Update. Ohne zeitgesteuertes Killen von Band-I/O.
Danach `sudo apt install ./opentape-archive-manager_<version>_all.deb` und
Dienste/Anmeldung/Jobzustände prüfen. Keine automatische Änderung von Plan oder
Verifikationsmodus. Konfiguration wird bei Updates erhalten.

`apt remove` bzw. `apt purge` entfernt Programmdateien. Katalog, lokale Konten,
Konfiguration, Staging, Quellen und Journale werden bewusst nicht gelöscht.
Die verbleibenden Daten enthalten vertrauliche Pfade und Zugangsdaten-Hashes;
eine spätere manuelle Datenlöschung ist eine gesonderte bewusste Entscheidung.

## Paket selbst bauen

Auf Debian aus dem gewünschten Git-Tag:

```sh
python3 packaging/debian/build.py --output dist
# dist/opentape-archive-manager_<version>_all.deb
```

Benötigt wird `dpkg-deb` (Paket `dpkg`); kein root, kein pip, kein Internet für den
Paketbau. Für die Installation müssen APT-Abhängigkeiten verfügbar sein. Die
Programmlizenz ist MIT; Debian-Abhängigkeiten behalten ihre jeweiligen Lizenzen.
