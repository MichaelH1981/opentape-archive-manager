# Wiederherstellung nach Verlust von Server, Datenbank und Installation

Diese Anleitung separat zusammen mit Formatbeschreibung, Exporten, Standalone-Recovery-Werkzeug und gegebenenfalls künftigen Schlüsseln offline aufbewahren. Die Banddatei 0 enthält zusätzlich RECOVERY.txt. Kleine reguläre physische Archiv-/Restore-Zyklen und der unabhängige GNU/Linux-Lesepfad sind auf IBM HH4/LTO-4 abgenommen; die allgemeine Produktionsfreigabe und große TARs werden weiter geprüft.

## 1. Verlust begrenzen

Band mechanisch schreibschützen, Beschriftung/ID dokumentieren. Auf Ersatzrechner Linux, funktionierender SAS-Controller und passendes LTO-Laufwerk, GNU tar, mt-st, mbuffer und Python 3 verwenden. Keine Initialisierung, kein Formatieren, kein Label-Schreiben. Automatische Backupdienste stoppen; Gerät exklusiv verwenden. Die vorhandenen Diagnose-Schreibskripte **nicht starten**.

Gerätezuordnung neu ermitteln; /dev/sg1 und /dev/nst0 sind keine stabilen Identitäten. `/sys/class/scsi_tape`, lsscsi und lesende Inquiry helfen. Nur das richtige nicht zurückspulende nst-Gerät nutzen. Blockmodus/Blockgröße aus dem späteren Hardware-Abnahmeprotokoll übernehmen; wenn dieses fehlt, erst schreibgeschützt fachkundig untersuchen, keine geratenen Schreib-/Formatierungsbefehle.

## 2. Banddateien unabhängig auf lokale SSD lesen

Nach bestätigtem Gerät und Blockmodus jede Banddatei in eine **neue** lokale Datei lesen. Das auf IBM HH4/LTO-4 bestätigte Rezept mit `mt`, GNU `dd bs=1M conv=excl`, expliziter BOT/FSF-Positionierung und Prüfung der Zähler steht in [Wiederherstellung ohne OTAM](recovery-without-otam.md). Variable Records dieses Profils sind höchstens 512 KiB groß; ein Read-Puffer von 1 MiB empfängt sie vollständig. Keine Padding-/Fehlerignorier-Optionen ergänzen. Für jede Datei von BOT aus positionieren; nie blind eine zusätzliche Filemark überspringen. Rückgabecodes, Bytezahlen und Hashes protokollieren. Falls Blockmodus oder Position unklar sind, stoppen.

Das konkrete Laufwerks-/Block-/Filemark-Profil und die unabhängigen Restore-Ergebnisse sind in `production-readiness.md` dokumentiert. Für andere Geräte-/Kernelprofile bleibt eine eigene Abnahme erforderlich. Die noch offenen allgemeinen Freigabesperren dürfen durch diese Anleitung nicht umgangen werden.

Beim Simulator einfach `.tar`-Dateien nummeriert kopieren; eine `.partial` ist kein bestätigtes Archiv. Kopien gegen versehentliche Änderungen schützen.

## 3. Identität und Format lesen

Mit GNU tar nur auf den **lokalen Kopien**:

```bash
tar -tf 00000000.tar
tar -xOf 00000000.tar -- media.json
tar -xOf 00000000.tar -- RECOVERY.txt
tar -xOf 00000001.tar -- OTAM/manifest.json
tar -xOf 00000002.tar -- receipt.json
sha256sum 00000001.tar
```

IDs und Format müssen zusammenpassen. Die ganze TAR-Prüfsumme muss dem Receipt entsprechen. Der Receipt des ersten Paars referenziert den SHA-256 des gesamten Header-TARs; jeder weitere den vorherigen Receipt-TAR. JSON und Pfade als Daten behandeln, niemals daraus Shellbefehle ausführen. Ein Hash auf demselben Medium bietet Integritätskontrolle, keine Manipulationsauthentizität.

## 4. Ohne OTAM wiederherstellen

Siehe [Wiederherstellung ohne OTAM](recovery-without-otam.md). Das eigenständige `tools/recover_tar.py` benötigt nur die Python-Standardbibliothek und zwei lokale TAR-Dateien; es verifiziert und extrahiert ausschließlich reguläre relative Nutzdaten in ein neues Verzeichnis. Kein OTAM-Paket, keine Datenbank, kein Internet nötig. Werkzeug ebenfalls offline sichern. Zur Not sind GNU tar und manuelle Manifest-/SHA-256-Prüfung ausreichend.

Fehlender Receipt: Daten sind nicht als abgeschlossene Sicherung bewiesen. Ein lesbares Manifest erlaubt fachkundige Rettung, aber Ergebnis als unvollständig behandeln und alle Dateien einzeln prüfen. Fehlerhafte Paare und unlesbare Bandbereiche dokumentieren; nicht den gesamten Bestand als VERIFIED erklären.

## 5. Katalog rekonstruieren

Für Simulator-Medien nach Verlust der SQLite-Datei:

```bash
python3 -m otam --db fresh.sqlite rebuild /pfad/zum/simulator --media-id BAND_UUID
python3 -m otam --db fresh.sqlite search
python3 -m otam --db fresh.sqlite restore /pfad/zum/simulator --media-id BAND_UUID --target /sicheres/neues/ziel
```

Header sowie jedes vollständige Daten-/Receipt-Paar werden erneut geprüft und inventarisiert. Ein partieller Tail wird gemeldet und sperrt das Medium. Bei mehreren Versionen --archive-id verwenden. Reales LTO-Katalogimport ist mit dem künftigen Adapter umzusetzen; derzeit kein CLI-Versprechen für physische Bänder.

Zum Abschluss Dateien am Ziel erneut prüfen (Werkzeug tut dies), Stichproben fachlich öffnen und Bericht samt Medien-ID archivieren. Bei künftig verschlüsselten Medien sind Schlüssel und Verfahren zwingend separat erforderlich. LUKS-/Boot-/Partitionen-Restore gehört zum späteren System-Snapshot-Workflow.
