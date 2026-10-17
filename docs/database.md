# SQLite-Schema und Migrationen

Quelle des ausführbaren Schemas: `otam/catalog.py`, SCHEMA und MIGRATION_2. `PRAGMA user_version=2`. Neue Datenbanken erhalten Migrationen 0→1 und 1→2 jeweils atomar in BEGIN IMMEDIATE/COMMIT; neuere Versionen werden abgelehnt. Für jede spätere Migration: transaktionales SQL, Backup via SQLite backup API, Upgrade-/Fehler-/Rollback-Test, niemals stillschweigend Tabellen verwerfen. Kein Downgrade.

| Tabelle | Zweck und zentrale Beziehungen |
|---|---|
| media | UUID, Klasse permanent/rotation, Label, Generation, native Kapazität, Hersteller/Seriennummer optional, first/last_use, Archivschreibanzahl, last_verified, Lagerort, state, used, vollständiger Header |
| jobs | UUID, Typ, Zustand, Medien-FK, Zeiten, unveränderlicher Plan samt Hash, Abschlussbericht, Fehler |
| archives | UUID, Medien-/Job-FK, eindeutige (media_id,tape_file), Zustand, Bytezahl, SHA-256, Datum, Manifest |
| files | Primärschlüssel (archive_id,path), Name, Größe, mtime_ns, Endung, SHA-256, optionaler tar_offset |
| events | fortlaufende ID, Job-FK, UTC-Zeit, Level, Ereignis, strukturiertes JSON |
| verifications | UUID, Job-/Archiv-FK, Zeitpunkt, Ergebnis, Fehler; Vollprüffehler kann ohne einzelnes Archiv erfasst sein |
| staged_archives | Phase/Zustand pro Job und Archiv, lokaler Root/Pfad, SHA-256, Bytezahl, Dateiidentität, Fortschritt, Fehler |
| staging_artifacts | Explizit registrierte Dateinamen und Geräte-/Inode-Identität; alleinige Löschkandidaten nach VERIFIED |
| storage_benchmarks | Persistente Lesetestberichte und Qualifikationsstatus, an Staging-Pfad und Dateisystem gebunden |
| restores | UUID, Job-FK, Ziel, Auswahlplan, Zustand |

Dateiverifikationsstatus wird aus archives.state abgeleitet; Archivierungszeit aus archives.created. Bandzugehörigkeit ebenfalls über archives. tar_offset bleibt NULL: kein verlässliches blockgenaues Seekversprechen innerhalb eines TARs. Das ganze TAR wird gelesen. files.type ist die Dateiendung, keine geprüfte MIME-Erkennung. Kopien/Dubletten über SHA-256 und Größe gruppieren; Treffer zeigen jede Archivkopie.

WAL, synchronous=FULL, foreign_keys=ON. Lokale SSD, keine SQLite-Datei auf NFS. Katalog sichern mit `sqlite3.Connection.backup` oder sqlite3 `.backup`, nicht nur die aktive Hauptdatei kopieren und WAL ignorieren. Exporte enthalten sensible Dateipfade und müssen entsprechend geschützt werden.

Medienzustände im Entwurf: UNKNOWN, TESTING, READY, IN_USE, FULL, ARCHIVED, SUSPECT, RETIRED. Nur READY/IN_USE erlauben Append. V1 stellt noch keine Verwaltungsbefehle für Retention oder Statusänderungen bereit. Rekonstruktion entsperrt bekannte ARCHIVED-/SUSPECT-Medien nicht automatisch. used ist logische TAR-Bytezahl, keine genaue physische Restkapazität; Reserve 5 %. writes zählt verifizierte Datenarchive, nicht alle physischen Write-Kommandos oder lebenslange MAM-Zähler. Unvollständige Versuche sind in Jobs/Events sichtbar.

Archivzustände: WRITING, VERIFIED, INCOMPLETE, SUSPECT. Jobzustände: PLANNING, PLANNED, STAGED, RUNNING, VERIFIED, FAILED, INTERRUPTED. STAGED ist kein Backup-Erfolg. jobs.phase und staged_archives.phase speichern INVENTORY, STAGING, VALIDATION, READY, TAPE_WRITE, TAPE_READBACK, VERIFIED, STAGING_CLEANUP; phase.state unterscheidet RUNNING/COMPLETE/FAILED/INTERRUPTED. Kein Write gilt als Erfolg ohne Rücklesung. Ein fehlgeschlagener Gesamtjob kann bereits verifizierte Teilarchive besitzen; sein report_json führt diese ausdrücklich auf. Bei Vollprüffehler werden bisherige Katalogarchive des Mediums konservativ SUSPECT, kein alter Erfolg wird als aktuelle Gesundheit ausgegeben.

Migration 1→2 erhält vorhandene Medien/Archive/Jobs. Noch nicht ausgeführte alte Pläne erhalten ihre INVENTORY-Datensätze beim Laden. schema_version im JSON-Export ist 2; Bandformat bleibt unverändert otam-pax-v1.
