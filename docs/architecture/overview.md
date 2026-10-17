# OTAM – Architekturentscheidung (2026-10-17)

Status: Phase 0 einschließlich lesender Server- und Skriptaufnahme dokumentiert; physische Bandabnahme ausstehend. Phase 1 wird zunächst ausschließlich gegen einen persistenten Simulator implementiert. Keine Freigabe für produktive Medien.

## Bestand und Grenzen
Die Entwicklung und die Simulatorprüfung erfolgen auf macOS und Linux. Eine lesende Serveraufnahme bestätigte Debian 13.7, Kernel 6.12.111, Python 3.13.5, GNU tar 1.35, mt-st 1.8 und mbuffer R20241007. Das IBM ULT3580-HH4 wurde zwischenzeitlich am SAS-HBA erkannt. Die Geräteanwesenheit ist veränderlich und wird vor späteren Hardwareaktionen erneut geprüft. Eine physische Bandabnahme und die Validierung von Filemarks, Positionierung und EOM stehen aus. Die bestehende SSD zeigte schwankenden Lesedurchsatz; ein zusätzlicher USB-HDD-Test ergab zonenabhängige Raten und Transport-Timeouts. Diese Befunde sind keine abgeschlossene SATA-Fehlerdiagnose. Private Netzwerk-/Gerätedetails und Rohprotokolle bleiben lokal. Siehe [Hardware-Abnahme](../hardware/README.md).

## Entscheidung
Python >=3.11, SQLite (WAL, foreign_keys, synchronous=FULL), Standard-PAX-TAR, SHA-256. CLI zuerst; ein Anwendungsdienst kapselt Planung, Archivierung, Prüfung und Restore. Der Hardwarevertrag kennt Medien-ID, unabhängige Banddateien, Lesen, Append und exklusive Sperre. Der Simulator implementiert diesen Vertrag mit Dateien auf Disk. Der Linux-Adapter bleibt bis zum Hardware-Gate schreibgesperrt.

PAX-TAR der Python-Standardbibliothek ist ein gleichwertiges offenes Format: streamingfähige Erstellung, keine Shell-Interpolation, vollständige Kontrolle über sichere reguläre Dateien und Manifest. GNU tar dient der unabhängigen Wiederherstellung. Reales Streaming soll später über mbuffer mit begrenztem RAM (auf diesem 8-GB-Server anfänglich 2 GiB, 90 % Vorfüllung gemäß vorhandener Diagnose) und mt-st erfolgen; keine automatische Mehrbandfortsetzung. Alle Pipeline-Rückgabecodes, Short Writes, Flush/Close und tatsächliches Rücklesen sind auszuwerten. Keine eigenen Treiber.

## Datenfluss
INVENTORY → STAGING → VALIDATION → READY → TAPE_WRITE → TAPE_READBACK → VERIFIED → STAGING_CLEANUP. Jede Phase wird dauerhaft gespeichert. Staging erfolgt vollständig auf lokalem persistentem Dateisystem, niemals direkter Netzquelle-zu-Band-Stream. Das originale lokale TAR bleibt bis zur vollständigen Verifikation erhalten. Rücklesung und SHA-256-Vergleich erfolgen im Stream ohne zweite große TAR-Datei. Siehe [verbindliche Staging-Spezifikation](../staging.md).

Eine Datei gehört genau zu einem Archiv. Ziel 75 GB dezimal; größere Dateien erhalten ein eigenes größeres Archiv. Die Planung überschätzt TAR-Overhead konservativ; beim Schreiben gilt zusätzlich die tatsächliche Größe. SSD muss das größte Archiv aufnehmen können. Kapazität nativ, ohne Kompressionsversprechen, mit 5 % Reserve. Unerwartetes EOM beendet den Job; kein Split, kein automatisches Wiederholen auf demselben Medium.

## Sicherheit und Zustände
Unbekanntes Medium nur lesend. Header-ID und Erwartungs-ID müssen übereinstimmen. Ein Prozess-Lock gilt für die gesamte Geräteoperation, unabhängig von der Datenbank. Auf Disk wird zusätzlich exklusiv angelegt; kein Seek-Write in vorhandene Banddateien. Ein unvollständiger Tail sperrt weiteres Append. SQLite ist kein Beweis der physischen Position. Eine ausdrückliche Wiederaufnahme liest deshalb die tatsächliche Bandsequenz vollständig erneut; ein partieller Tail sperrt weiteres Write. Kein automatisches Löschen, Formatieren, Überschreiben oder Recyceln, auch für rotierende Medien.

Job: PLANNED → RUNNING → VERIFIED oder FAILED; nach Neustart RUNNING → INTERRUPTED unter Sperre. Archiv: WRITING → VERIFIED oder INCOMPLETE. Ein Receipt ist erst nach vollständiger Rücklesung zulässig; nach einem Crash wird nichts erneut geschrieben. Ein späterer Scan kann vollständig prüfbare Paare rekonstruieren. Fehlerverdächtige Medien benötigen manuelle Untersuchung. Datenbankverlust darf keine Medieninitialisierung auslösen.

Phase 1 archiviert reguläre Dateiinhalte, Pfade, Größen und mtime. Links, Geräte, FIFOs, Sockets werden abgelehnt. Keine ACLs/xattrs, Besitzerübernahme, leeren Verzeichnisse oder System-Restore in Phase 1. Quellen müssen ruhen bzw. aus Snapshots kommen; eine konsistente Gesamtsicht aktiver Dateisysteme lässt sich mit Datei-Hashes allein nicht garantieren. Restore erzeugt nur reguläre Dateien mit Modus 0600, prüft Hashes und folgt keinen Ziel-Symlinks; vorhandene Dateien führen zum Fehler. Keine generische extractall()-Verwendung.

## Erweiterungspunkte
Phase 2: mehrere Medien, geführte Wechsel, größere Kataloge, Filter, Katalogimport und selektiver Restore. Basisfunktionen können in Phase 1 vorgezogen werden. Medienklassen und Metadaten sind bereits im Schema vorgesehen.

Phase 3: lokaler HTTP-Dienst mit REST /api/v1, serverseitigem Job-Worker und responsiven Ansichten (Dashboard, Medien, Archive, Suche, Jobs, Restore, Prüfungen, Hardware, Einstellungen, Logs). Bind 127.0.0.1; andere interne IP nur explizit. Vor Mutationsendpunkten Authentifizierung, CSRF-/Origin-Schutz und Planbestätigung; kein beliebiger Shellzugriff. Fortschritt wird in SQLite gespeichert; polling/SSE, Safari ohne Spezial-APIs. systemd ohne root; nur erforderliche Tape-Geräte, keine Telemetrie.

Phase 4: TapeAlert/LOG SENSE via etablierte Tools (z.B. sg_logs/smartctl; verfügbarkeitsabhängig), Retention-Vorschläge mit separater destruktiver Freigabe, System-Snapshots, Berichte, Verschlüsselung. Hashes beziehen sich auf Klartextdateien und archivierten Bytestrom; encryption descriptor speichert Verfahren/Version/Key-ID, niemals Schlüssel. Schlüssel und Wiederherstellungswerkzeuge separat sichern. Öffentliches Medieninventar und optional verschlüsseltes Detailmanifest getrennt spezifizieren. LTO-Hardwareverschlüsselung erst nach capability-Abfrage und Restore-Test.

## Lizenz
Neue OTAM-Dateien unter MIT (LICENSE). Keine fremden Projektquellen übernommen. Aufrufe separater GNU-Werkzeuge und deren eigene Lizenzen dokumentieren; bei späterer Übernahme von AGPL-Code Lizenzentscheidung neu treffen.
