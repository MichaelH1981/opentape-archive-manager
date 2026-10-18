# Softwaretests und physische Abnahme

## Automatisierte Tests (ohne Bandhardware)

Aufruf: `python3 -m unittest discover -v`. Nur temporäre reguläre Testdateien; Tests greifen niemals auf /dev/nst* oder /dev/sg* zu. LinuxTape ist ausdrücklich schreibgesperrt.

Abgedeckt: vollständiger Plan→Append→Rücklese→VERIFIED→Restore-Zyklus, unveränderte frühere Banddateien nach Append, mehrere TARs, übergroße ungeteilte Einzeldatei, konservative Kapazität und EOM, falsches Medium, Prozesssperre, falsche/erneute Bestätigung, stale/manipulierter Plan, Quellenänderung trotz gleicher Größe/mtime, Schreib-/Lesefehler, Receiptfehler, unterbrochener Write, abruptes os._exit nach Receipt vor DB-Commit, Neustartstatus, Katalogverlust/Rekonstruktion, atomare Rekonstruktion bei Konflikt, unvollständiger Tail mit früheren gültigen Paaren, beschädigte Daten/Hashkette, fehlende Dateien, Pfadtraversal/absolute Pfade/Links/Geräte, Ziel-Symlinks/kein Überschreiben, kein Restore ins Medium, neuere DB-Version, Suche/Kopien/CSV, unabhängiges tar-Lesen und Standalone-Restore mit isoliertem Python.

Ergebnis am 17.10.2026: Tests unter macOS ARM64 / Python 3.14.7 und Debian 13.7 x86_64 / Python 3.13.5, GNU tar 1.35 bzw. bsdtar 3.5.3. Linuxlauf erfolgte als michael in einem neuen /tmp/otam-software-test-*-Verzeichnis; dieses wurde automatisch entfernt. Keine Installation, keine Paketänderung, keine produktiven Quellen und keine Bandgeräte. Endgültige Testanzahl siehe Abschlussprotokoll unten. Deklarierte Python-Untergrenze 3.11 noch nicht separat getestet.

Der Simulator testet weder echten SCSI-EOM/early warning noch Filemarks, Treiberpuffer, Laufwerkswechsel, Hardwarekompression, TapeAlert oder mechanische Streamingstabilität. Fault-Injection ist kein Beweis dafür. Große Datenmengen und Millionen Dateien wurden in OTAM noch nicht profiliert.

## Hardwareabnahme: separat und ausdrücklich freigabepflichtig

Vorbereitung ohne Write: vorhandene Skripte prüfen (erledigt), Distribution/Tools/Controller aus sysfs erfassen (erledigt), aktuelle Gerätezuordnung und Seriennummer, Blockmodus, Schreibschutz und TapeAlert feststellen (Laufwerk derzeit nicht vorhanden). Keine automatische sudo-Nutzung.

Erst nach **ausdrücklicher Freigabe eines konkret benannten entbehrlichen Testbands**:

1. Medien-ID, physisches Etikett und vorhandenen Inhalt dokumentieren. Freigabe gilt nur für dieses Medium und den genannten Testumfang.
2. Reale Adapter-Implementierung getrennt reviewen; Befehls-Allowlist, systemweite Gerätesperre und alle Pipelinefehlerpfade prüfen. Fremde Backupdienste ausgeschlossen.
3. Kleine Header-/Daten-/Receipt-TARs schreiben; Close/Filemark-Modus, EOF-Position und BOT+fsf-Positionierung unabhängig prüfen. Keine zusätzliche Filemark aufgrund einer Annahme.
4. Append nach Neustart, nach Rewind/Read und nach Medienwechsel; jedes frühere Byte erneut vergleichen. Falsche ID und unbekannte Position müssen Write verhindern.
5. Lange Streams mit realistisch langsamer Quelle bzw. SSD-Staging; Pufferfüllung, CPU/RAM/SSD und Fehlerzähler protokollieren. Bekannte 2-GiB-/90-%-Werte nur als Startpunkt.
6. Explizit freigegebener EOM-/Abbruchtest: kein Split, kein Replay über unvollständigen Tail, frühere Archive lesbar. Kein Stromziehen an produktiver Hardware; kontrolliertes Prozessende bevorzugen.
7. Alles vollständig zurücklesen und SHA-256 prüfen. Katalog löschen nur als **Kopie im Testverzeichnis**, danach frische Installation und unabhängiger GNU-tar-/Standalone-Restore.
8. Ergebnis samt Kernel, Firmware, Tools, Blockgrößen, Filemarks und Restore-Rezept festhalten. Erst danach Produktionsfreigabe erwägen.

Gebrauchtmedien-Qualifikation bleibt destruktiv, standardmäßig deaktiviert und außerhalb der automatisierten Tests. Die vorhandenen tape-certify-Skripte ersetzen keinen OTAM-Append-/Katalog-/Positionierungstest. Gesundheitszähler sind Hinweise, keine Lebensdauerprognosen.

## Abschlussprotokoll 17.10.2026

- **28/28 PASS**: macOS ARM64, Python 3.14.7, rund 0,31 s.
- **28/28 PASS**: Bandserver Debian 13.7 x86_64, Python 3.13.5, GNU tar 1.35, rund 0,78 s.
- **PASS**: zusätzlicher CLI-Prozesszyklus init-sim → plan → backup → verify → restore-plan → restore → search → export; Zieldatei bytegleich, Quelle unverändert.
- **PASS**: compileall für otam, tools und tests.
- Kein physischer Bandtest durchgeführt. Keine Installation/Änderung bestehender Skripte; remote Softwaretests ausschließlich in automatisch entfernten neuen temporären Verzeichnissen.

## Ergänzung: Staging-Anforderung 20 (Version 0.2)

Die Suite enthält jetzt 50 Tests. Zusätzlich geprüft: persistente Phasen, schreibgeschütztes READY, unabhängiges Staging ohne Laufwerk, Weiterverwendung nach Neustart und verschwundener Quelle, unterbrochenes Staging/Publikation, Erhalt nach Tape-Write-/Readbackfehler, Manipulation vor Write, Cleanup nur für registrierte eigene Inodes, Fremddateien/Symlinks, geringe Staging-Kapazität, prepare-all vor erstem Write, gemeinsame I/O-Sperre, NFS/tmpfs/opaque Blockgeräte, lokale dm-Abhängigkeiten, Streaming-Rücklesung ohne zweite TAR-Datei und mit vollständigem Padding-Hash, explizite Wiederaufnahme ohne erneutes Schreiben bestätigter Paare, Schema-Migration 1→2 und CLI-Monitoring.

- macOS/Python 3.14.7: **49 bestanden, 1 Linux-O_DIRECT-Test plattformbedingt übersprungen**.
- Debian/Python 3.13.5: **50/50 bestanden**; temporäre Testverzeichnisse auf SSD unter /var/tmp, anschließend entfernt.
- Der erste Debian-Versuch unter /tmp wurde durch die neue tmpfs-Sperre abgewiesen. Die Sperre blieb erhalten; die Tests wurden auf persistente lokale SSD verlegt.
- Der Linux-Benchmark-Funktionstest verwendet ausschließlich eine synthetische 8-MiB-Datei für etwa 0,03 Sekunden. Ergebnis bewusst qualified=false. **Kein 30-Minuten-Test und keine Produktions-Leistungsfreigabe durchgeführt.**
- Reale mbuffer-/nst-Integration und Puffer-/Positionierungs-Telemetrie bleiben Teil der gesonderten physischen Abnahme. Keine Bandzugriffe oder produktiven Quelldatenänderungen.

Für Tests auf Linux kann OTAM_TEST_TMPDIR ein neues Testverzeichnis auf lokalem persistentem Dateisystem vorgeben. Standard ist /var/tmp; /tmp kann tmpfs sein und ist kein Staging-Ersatz.

## Web- und Standalone-Katalog-Abnahme (Version 0.3)

Mit installierter Web-Laufzeit umfasst die Suite 70 Tests. Auf dem Debian-Archivserver bestanden alle 70 in einer eigens angelegten und anschließend entfernten Umgebung unter /var/tmp; keine Systeminstallation und keine Bandzugriffe. Auf macOS wird der Linux-O_DIRECT-Test übersprungen. Neue Tests prüfen HTTP-Archivzyklus, authentifizierte Rollen/CSRF/Origin/Host, durable/idempotente Queue, Workerexklusivität, Filter/Pagination/Kopien, sichere Exporte, Restore ohne Überschreiben, vollständige Snapshotvalidierung/Replay/Orphan-Recovery, NAS-Zielmarker und ausdrücklich bestätigte Staging-Nachprüfung.

Zusätzliche manuelle Browserabnahme: Planung und lokales Staging per Formular, bestätigter Simulator-Archivjob, Dateisuche/Auswahl und erfolgreicher Einzeldatei-Restore; unabhängige Catalog-Node-Weboberfläche nach tatsächlichem Stoppen von Archive-Webdienst und Worker weiterhin durchsuchbar. Zwei Archivkopien derselben Datei wurden am eigenständigen Node angezeigt. Responsive Prüfung im In-App-Browser auf Desktop- und Mobilbreiten; dies ersetzt keine tatsächliche iPhone-Geräteabnahme. Der Container-Imagebau und die reale Proxmox-/NAS-Installation sind mangels vorhandener Zielumgebung nicht abgenommen.

## Expliziter kleiner Bandlayout-Test

`tools/tape_layout_acceptance.py` ist ein **separater destruktiver Hardwaretest**,
kein Bestandteil der automatisierten Tests. Ausschließlich für ein ausdrücklich
freigegebenes entbehrliches Medium: Laufwerk und MAM-Seriennummer müssen exakt
angegeben und mit `--confirm 'TESTEN <Laufwerks-SN> <Medien-SN>'` bestätigt werden.
Der reguläre Worker muss zuvor ohne aktive Aufträge pausiert sein. Der Test läuft
als unprivilegierter Workerbenutzer mit dessen Tape-Gerätegruppe, gleichem TMPDIR
und `--state`-Verzeichnis; er hält Worker-, I/O- und Gerätesperre.

`--output` muss ein neues privates Verzeichnis auf einem bestätigten lokalen,
schreibbaren Dateisystem mit mindestens 512 MiB freiem Platz sein. Es werden nur
eigene synthetische Quelldateien und vollständig lokale PAX-TARs erstellt, keine
externen Nutzdaten akzeptiert. Das bestehende Band wird ab BOT überschrieben.
Header, Daten und Receipt werden einzeln geschrieben und vollständig zurückgelesen.
Receipts erhalten erst nach erfolgreichem tatsächlichem Daten-Readback einen
Verifikationszeitpunkt. Vor Append wird der bestehende vollständige Präfix erneut
gelesen; EOD muss die erwartete Banddatei und Blockposition 0 melden. Jede
unbekannte Position führt zum Abbruch, ohne Schreibversuch an dieser Position.
Nach Append werden sämtliche vorherigen und neuen Banddateien in anderer
Reihenfolge mit BOT+fsf gelesen und komplett gehasht; GNU tar prüft ihre Lesbarkeit.
Job-ID, Bewegungen, Positionen, Hashes und Abschlussstatus werden atomar im
Testverzeichnis gespeichert. Bei Fehlern kein automatischer Neustart oder Replay.

Auch ein erfolgreicher `LAYOUT_READBACK_VERIFIED`-Test ersetzt weder vollständige
Medienqualifikation noch EOM-/Abbruch-/Medienwechselabnahme und schaltet keinen
produktiven Backendzugriff frei. Standalone-Restore und Katalogrekonstruktion
können anschließend ausschließlich mit den lokalen Test-Rücklesedateien geprüft
werden. Produktive Kataloge dürfen dafür nicht gelöscht werden.
