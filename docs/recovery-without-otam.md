# Wiederherstellung ohne OTAM

Alle Eingaben sind bereits auf SSD kopierte Banddateien. Originalmedium schreibgeschützt lassen. Kein OTAM-Modul wird für dieses Verfahren benötigt.

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
