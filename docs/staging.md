# Verbindliches lokales Staging (Anforderung 20)

Alle regulären Archivjobs erstellen ihre TARs vollständig auf lokaler Platte/SSD. NAS, Nextcloud, SSHFS und andere Netzquellen werden ausschließlich während INVENTORY/STAGING gelesen. Der Bandadapter bekommt nur ein vollständig validiertes lokales TAR, niemals einen Quellstream. Staging ist keine unabhängige Sicherung.

## Persistenter Ablauf

`INVENTORY → STAGING → VALIDATION → READY → TAPE_WRITE → TAPE_READBACK → VERIFIED → STAGING_CLEANUP`

SQLite-Schema 2 speichert pro Archiv Phase, Zustand, Fortschritt, Zeit, Fehler, Staging-Pfad, vollständigen SHA-256, Bytezahl und Dateiidentität. `jobs.phase` zeigt die aktuelle Jobphase; events protokollieren die Übergänge. COMPLETE in READY bedeutet nur fertig vorbereitet, nicht gesichert. Erst nach tatsächlichem vollständigem Rücklesen einschließlich TAR-Padding und erfolgreichem Vergleich zum ursprünglichen lokalen TAR-Hash wird das Archiv VERIFIED. Auch der anschließende Band-Receipt muss erfolgreich geschrieben und zurückgelesen sein.

Das TAR bleibt **bis nach VERIFIED** auf SSD erhalten. Die Rücklesung läuft durch einen begrenzten Stream-Parser und SHA-256-Zähler, ohne zweite große lokale TAR-Datei. Datei-Manifeste werden im selben Rücklesedurchgang geprüft; der Rest bis EOF/Filemark wird ebenfalls gehasht. Erfolgreiches Schreiben oder gleiche Bytezahl allein genügen nicht.

## Staging-Verzeichnis und Platz

`--staging /srv/otam/staging` ist frei wählbar; Standard `.otam/staging`. Das bisherige `--spool` bleibt Alias. Der Pfad muss außerhalb Quelle, Katalog und Medium liegen. Ein laufender Job bleibt an seinen ersten Staging-Pfad gebunden.

Linux: längster passender Mount aus `/proc/self/mountinfo` (auch Bind-/Unter-Mounts und maskierte Leerzeichen). Bekannte lokale persistente Dateisysteme werden zugelassen; NFS/CIFS/SSHFS, tmpfs, Overlay und unbekannte Typen abgelehnt. macOS-Entwicklung: mount plus df-Zuordnung für APFS-Firmlinks. Unklare Lokalität führt zum Abbruch, kein Override. Auf dem Bandserver liegt `/tmp` auf tmpfs; für Tests `/var/tmp` auf SSD verwenden.

Zusätzlich wird unter Linux die sichtbare sysfs-Blockgeräteabhängigkeit geprüft, auch bei dm/md. iSCSI-Sessions, NBD/RBD/DRBD, NVMe TCP/RDMA/FC, Loop-/opaque virtuelle Geräte und nicht nachweisbare Backings werden abgelehnt. Komplexe ZFS-/Mehrgeräte-Btrfs-/Virtualisierungskonfigurationen ohne eindeutig sichtbaren lokalen Blockpfad sind damit zunächst nicht freigegeben. Diese konservative Prüfung ersetzt keine Serverabnahme der physischen Verkabelung. Reale Bandschreibzugriffe bleiben bis zur Hardwareabnahme gesperrt.

Vor Jobstart wird der geschätzte Platzbedarf geprüft, vor jedem Archiv erneut. Normalbetrieb benötigt Platz für das größte einzelne TAR plus kleinen Receipt, nicht für ein ganzes Band. Erst nach Verifikation/Bereinigung wird das nächste TAR erstellt. `--prepare-all` verlangt vorab Platz für alle fehlenden TARs. `stage JOB` bereitet ebenfalls den gesamten Plan ohne Laufwerkszugriff vor. Frühere Fehlversuche belegen weiterhin Platz und werden nicht als frei angenommen. Dateisystemfreie Kapazität ist eine Momentaufnahme, keine Reservierung gegen fremde Prozesse; ENOSPC wird als Fehler behandelt und erreicht nie READY.

## Veröffentlichung und Wiederaufnahme

Eigene Unterverzeichnisse `otam-JOB_UUID/ARCHIV_UUID/` mit owner.json, eindeutigen `.partial`-Versuchen, `ready.tar` und kleinen Receipts. Inhalte werden fsync-gesichert, gegen Manifest geprüft, vollständig gehasht, schreibgeschützt und exklusiv veröffentlicht. SQLite enthält Gerät/Inode/Größe/mtime/ctime. Direkt vor Write werden lokale Lage, Identität, Schreibschutz, TAR-Konsistenz und SHA-256 erneut geprüft. Nach Write/Readback ebenfalls keine stillschweigende Akzeptanz eines veränderten Staging-TARs. Schreibschutz schützt vor versehentlichen Änderungen; absichtliche Eingriffe durch denselben Benutzer/root sind keine zugesicherte Dateisystem-Immutable-Garantie und führen bei Erkennung zum Abbruch.

Nach Neustart werden READY-Dateien neu geprüft und weiterverwendet, auch wenn die ursprüngliche Quelle nicht mehr erreichbar ist. Ein Crash während exklusiver Veröffentlichung wird anhand des persistenten Veröffentlichungsauftrags und der registrierten Inode nachvollzogen. Ein unvollständiger STAGING-Versuch wird unter neuem eindeutigen Namen neu begonnen; alter Inhalt bleibt bis zur späteren erfolgreichen Verifikation erhalten. Kein Überschreiben des Fehlversuchs und kein voreiliges Entfernen fertiger TARs.

`backup --resume` ist eine ausdrückliche Wiederaufnahmeentscheidung mit derselben bestätigten Job-ID. Es prüft Medien-ID, Zustand, tatsächliche zusammenhängende Banddateien, vollständige Rücklesung und Receipts erneut. Bereits abgeschlossene Paare müssen exakt dem Plan und ursprünglichen Staging-Hash entsprechen; sie werden nicht erneut geschrieben. Ein unvollständiger Tail, fremde Archive oder eine nicht beweisbare Position sperren jede Fortsetzung. ARCHIVED/RETIRED-Medien werden nicht entsperrt. Ein verifizierbarer Abschluss nach Crash kann übernommen und danach aufgeräumt werden. Kein automatisches Zurückschreiben/Überschreiben zur „Reparatur“.

Cleanup benötigt einen in SQLite VERIFIED gespeicherten Archivabschluss. Nur einzeln registrierte eigene temporäre Dateien mit passender Inode/Gerät werden entfernt. Keine rekursive Verzeichnislöschung. Fremde Dateien und owner.json bleiben erhalten, ausgetauschte Dateien/Symlinks führen zum Fehler. Ein Fehler beim Cleanup ändert den bereits verifizierten Archivinhalt nicht; der Job meldet den Fehler und kann nach Untersuchung ausdrücklich wiederaufgenommen werden.

## Entkopplung und Monitoring

Eine gemeinsame exklusive OTAM-I/O-Sperre pro Unix-Benutzer und temporärem Systemverzeichnis serialisiert Inventarisierung, Staging, Benchmark, Bandjobs und umfangreiche Restore-/Prüfjobs, auch über verschiedene Kataloge/Staging-Pfade. Keine OTAM-Staging-Arbeit parallel zum Bandstream. Dedizierten Dienstbenutzer und einheitliches TMPDIR verwenden; fremde Prozesse/andere Benutzer werden dadurch nicht gedrosselt und müssen bei der Betriebsabnahme berücksichtigt werden.

`staging-status` zeigt Dateisystem, Kapazität/freie Bytes, Archivphasen und Fortschritt; SQLite-events enthalten Staging-Fortschritt sowie Schreib-/Rücklesebytes und Rate. Der Simulator liefert für Pufferfüllstand und physische Positionierungen ausdrücklich null, niemals erfundene Hardwarewerte. Webdarstellung folgt Phase 3. Der reale Adapter muss mbuffer-Status, Laufwerksfehler und Positionierungsereignisse in die Monitor-Schnittstelle liefern. Reales mbuffer-Streaming ist weiterhin nicht implementiert/freigegeben. Ausgangspunkt laut bestehender Diagnose: 2 GiB Puffer, 90 % Vorfüllung; Rate/Blockmodus erst am Testband abnehmen.

## Lesender Leistungstest vor Produktion

`staging-benchmark` liest eine bereits vorhandene reguläre lokale Staging-Datei mit Linux O_DIRECT und ausgerichtetem 4-MiB-Puffer. Er schreibt/löscht keine Testnutzdaten, verwendet keinen gecachten Ersatzpfad und läuft unter derselben I/O-Sperre. Samples im Abstand von mindestens einer Sekunde erfassen die tatsächlich verstrichene Zeit einschließlich Stalls; jeder Sample und der Abschluss werden gespeichert.

```bash
python3 -m otam --db /lokaler/pfad/catalog.sqlite staging-benchmark \
  --staging /srv/otam/staging --file /srv/otam/staging/otam-JOB/ARCHIV/ready.tar \
  --seconds 1800 --min-rate 120000000
```

Qualifikation nur bei mindestens 30 Minuten, mindestens 10 GiB echter Eingabedatei, Direct-I/O und **jedem Messfenster ≥120.000.000 Bytes/s**. Kürzere Tests oder kleinere Dateien sind ausschließlich Funktionstests und liefern qualified=false/Exit 1, auch bei hohem Durchschnitt. Der gesamte Messbericht enthält Durchschnitt, Minimum, Samplezeiten und Dateisystemzuordnung. Für nicht simulierte Backends prüft der Schreibworkflow zusätzlich, ob ein bestandener Test für denselben Staging-Pfad und dieselbe Dateisystemidentität vorliegt; dies ersetzt nicht das separate physische Hardware-Gate.

Sync-QD1-Direct-I/O prüft bewusst einen konservativen sequenziellen Leser. Vorhandene Diagnose zeigte starke SSD-Einbrüche bis 29 MiB/s und bessere QD8-Werte. Ein zu schlechter Test darf nicht durch einen kurzen Durchschnitt oder stillen Cache-/Queue-Wechsel „bestanden“ werden. Bei Bedarf einen anderen validierten Datenpfad oder eine andere lokale Platte separat qualifizieren. 2 GiB Puffer überbrücken kurze Einbrüche, kein dauerhaftes NAS-Durchsatzdefizit. Wiederholung unter realistischer konkurrierender Systemlast und mit typischen TAR-Größen gehört zur Betriebsabnahme; kein kurzer Softwaretest beweist 120 MB/s dauerhaft.

Inzwischen wurde der vollständige 30-Minuten-Test auf der lokalen Server-SSD durchgeführt: [lokale Diagnose und Hardware-Abnahme](hardware/README.md). Durchschnitt 254,73 MB/s, Minimum 26,15 MB/s, qualified=false. **Keine Produktionsfreigabe**; ein hoher Durchschnitt ersetzt die geforderte stabile Rate nicht. Es wurde kein produktiver Bandjob durchgeführt.
