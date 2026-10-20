# Wiederherstellung ohne OTAM

Die Extraktion arbeitet mit lokal kopierten Banddateien. Der erste Abschnitt beschreibt deren unabhängiges Lesen vom Band. Originalmedium schreibgeschützt lassen. Kein OTAM-Modul wird für dieses Verfahren benötigt.

## Banddateien ausschließlich mit Linux-Werkzeugen lesen

Am 20.10.2026 auf dem IBM HH4 mit LTO-4 geprüft: Header, erster Daten-TAR und
Receipt wurden mit `mt-st` und GNU `dd` gelesen, anschließend mit System-Python
ohne OTAM-Importe wiederhergestellt. Das Ergebnis stimmt mit dem ursprünglichen
Archiv-SHA-256 überein. Dies bestätigt diesen Lesepfad; die allgemeine
Produktionsfreigabe bleibt eine gesonderte Abnahme.

Laufwerk und MAM-Medienseriennummer zuerst mit `sg_inq`/`sg_read_attr` feststellen.
Alle Backup-/Wartungsdienste anhalten und das Gerät exklusiv verwenden. Das Medium
möglichst mechanisch schreibschützen. Die folgenden Gerätenamen sind Platzhalter
und müssen durch das eindeutig erkannte Non-Rewinding-Gerät ersetzt werden.
Ausgabedateien müssen neu sein; ausreichend lokalen Platz für TARs und die
Wiederherstellung vorhalten. Keine dieser Aktionen initialisiert ein Band.

```bash
mkdir recovery-files
cd recovery-files
mt -f /dev/nstX setblk 0
mt -f /dev/nstX rewind
mt -f /dev/nstX status
# Nur bei bestätigtem File number=0, block number=0 fortfahren:
dd if=/dev/nstX of=00000000.tar bs=1M conv=excl status=progress
tar -xOf 00000000.tar media.json

mt -f /dev/nstX rewind
mt -f /dev/nstX fsf 1
mt -f /dev/nstX status
# File number=1, block number=0 prüfen:
dd if=/dev/nstX of=00000001.tar bs=1M conv=excl status=progress

mt -f /dev/nstX rewind
mt -f /dev/nstX fsf 2
mt -f /dev/nstX status
# File number=2, block number=0 prüfen:
dd if=/dev/nstX of=00000002.tar bs=1M conv=excl status=progress
```

Jedes Kommando muss erfolgreich enden; bei Lesefehlern oder unklarer Position
stoppen. GNU `dd` liest mit diesem Muster bis zur ersten physischen Filemark.
`bs=1M` ist groß genug für die vom OTAM-Profil geschriebenen 512-KiB-Records.
Ein zu kleiner Read-Puffer kann beim Linux-st-Treiber ENOMEM verursachen, obwohl
genügend RAM frei ist. **Keine** Optionen `sync`, `noerror` oder `fullblock`
ergänzen: Fehler dürfen weder übergangen noch Bytes aufgefüllt werden. `conv=excl`
verhindert das Überschreiben bereits vorhandener Ausgabedateien.

Für weitere Paare die bestätigten Positionen 3/4, 5/6 usw. verwenden; jeweils von
BOT neu positionieren. Keine zusätzliche Filemark-Positionierung aus einer bloßen
Annahme über die Position nach Close ableiten. Medien-ID im Header und in jedem
Receipt prüfen, Datenhash und Bytezahl vergleichen und die `previous`-Hashkette
vom Header über alle Receipts verfolgen. Das separate, ausschließlich lesende
Abnahmewerkzeug `tools/tape_gnu_recovery_acceptance.sh` automatisiert einen solchen
ersten Paar-Test mit Identitäts- und Zugriffssperren, ohne ein OTAM-Modul zu laden.

## Eigenständiges Werkzeug

`tools/recover_tar.py` ist ein kleines eigenständiges Python-3-Programm ohne Abhängigkeiten außerhalb der Standardbibliothek. Es prüft vollständigen TAR-Hash und Bytezahl, Archiv-/Medien-ID, sämtliche Manifestdateien und das tatsächliche Ziel nach dem Schreiben. Es übernimmt keine gefährlichen Metadaten. Ziel muss neu sein und in einem vertrauenswürdigen existierenden Elternverzeichnis liegen; als normaler Benutzer ausführen.

```bash
python3 -I recover_tar.py 00000001.tar 00000002.tar /sicheres/elternverzeichnis/archiv-1
```

Jedes Archiv in ein eigenes neues Ziel wiederherstellen; dadurch bleiben verschiedene Versionen gleicher Pfade unterscheidbar. Der Standalone-Helper prüft jeweils ein Paar. Die Verkettung aller Receipts und den Header separat wie im Bandformat beschrieben prüfen. Bei Fehler ist das Ziel unvollständig; keine Erfolgsannahme. Erneuter Lauf braucht ein neues Ziel. Die Tests führen dieses Werkzeug mit `-I` aus, ohne installierbares OTAM-Paket oder Katalog.

## Ausschließlich GNU tar und SHA-256

Manifest und Receipt mit `tar -xOf` anzeigen. Receipt-Hash mit `sha256sum DATEN.tar` vergleichen; IDs, Bytezahl und Format prüfen. Inhalt mit `tar -tvf` kontrollieren: nur `OTAM/manifest.json` und reguläre `data/...`-Mitglieder. Absolute Pfade, `..`, Links, Geräte und doppelte Mitglieder ablehnen. Nie ungeprüft als root extrahieren.

Eine bekannte einzelne Datei lässt sich ohne Pfadextraktion lesen:

```bash
mkdir neues-ziel
cd neues-ziel
set -C
tar --extract --to-stdout --occurrence=1 --file=/sicherer/pfad/00000001.tar -- 'data/fotos/beispiel.jpg' > beispiel.jpg
sha256sum beispiel.jpg
```

`set -C` verhindert Überschreiben durch die Shell-Umleitung. Den angezeigten Hash und die Größe mit dem Manifest vergleichen. Für jede weitere Datei wiederholen; erwartete Dateien müssen vollständig vorhanden sein. `--occurrence=1` ist kein Ersatz für vorherige Ablehnung doppelter Mitglieder. Das maschinenlesbare JSON-Manifest erlaubt eigene unabhängige Implementierungen; SHA-256 wird über unveränderte Dateibytes berechnet, nicht über Dateinamen oder Zeitstempel. TAR-Datei-Hash und Einzeldatei-Hashes sind verschiedene Prüfsummen.
