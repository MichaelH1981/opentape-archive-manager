# Entwicklung

Module: common (Sicherheit/I/O), archive (Inventar/PAX/Hashes), tape (Hardwarevertrag/Simulator), catalog (Schema/Transaktionen), service (Workflows), restore (sichere Extraktion), hardware (lesende Erkennung), staging/storage (persistente lokale Bereitstellung und I/O-Sperre), benchmark (Direct-I/O-Lesetest), cli (Transport). tools/recover_tar.py bleibt bewusst unabhängig, um Recovery ohne Installation nachzuweisen. Keine UI-Bibliothek und kein externer Dienst in Phase 1.

```bash
python3 -m unittest discover -v
python3 -m compileall -q otam tools tests
```

Tests erzeugen ausschließlich neue temporäre Verzeichnisse und reguläre Dateien. Keine /dev-Geräte, keine Shell-Skripte des Bandservers, kein sudo. Fault-Injection über SimulatedTape(fail_after=..., read_error=..., interrupt_after=...); EOM über Kapazität und kontrollierte Adapterfehler. Abrupter Prozessverlust zusätzlich über separaten Prozess mit os._exit, damit kein Python-finally den Zustand bereinigt.

Ein neuer Adapter muss Tape erfüllen: locked gilt für volle Workflow-Laufzeit, header liefert unverwechselbare ID/Format, positions listet zusammenhängende unabhängige Banddateien, read gibt kleine Metadaten bzw. für Restore eine lokal lesbare Datei zurück; open_read liefert Datenarchive als echten Rücklesestream, append akzeptiert erwartete Medien-ID und schreibt ausschließlich an validiertem Ende, used/has_partial sind konservativ. Reales Readback darf das nächste Archiv nicht durch eine Speicherreferenz simulieren. Das ursprüngliche Staging-TAR bleibt bis VERIFIED erhalten; verify_stream prüft Rücklesedaten ohne zweite große Datei. set_monitor liefert Transferbytes, Rate und verfügbare Hardwarewerte. Der jetzige Simulator liest dieselben persistierten Diskdateien tatsächlich erneut; das modelliert Integritätslogik, keine Tape-Physik.

Keine freie Shell-Kommandozeichenkette aus Benutzerpfaden. Für externe Werkzeuge Argumentlisten, check/Timeouts und Pipe-Rückgaben aller Prozesse auswerten. Nicht fsync auf Band erzwingen (bekannter EINVAL-Fall); stattdessen validierte Close/Filemark-/Flush-Semantik. fsync im Simulator betrifft normale Diskdateien.

Wiederaufnahme nur per ausdrücklichem --resume nach vollständiger erneuter Medien-/Positionsprüfung; keine automatischen Retry-Writes nach Abbruch, keine „Reparatur“ durch Entfernen des Tails. Schemaänderungen als Migration, Formatänderungen versionieren, Rückwärtslesen bestehender Medien testen. Große Kataloge sind noch nicht profiliert: Inventar/Plan liegen derzeit in RAM und JSON, daher Phase-1-Preview für begrenzte Dateianzahl; später chunkweise DB-Planung. Höchstgröße des Manifests erzwingt eine explizite Fehlerantwort.

Aktuell werden vor Append konservativ alle vorhandenen Archive erneut gelesen. Ein beschädigtes früheres Paar kann den Scan und automatischen Restore späterer Paare blockieren; eine gesonderte Forensikfunktion gehört nicht zum Erfolgsworkflow. Keine Effizienzbehauptung für die spätere physische Bewegung. Joblog besteht aus dauerhaftem SQLite-events-JSON, keine separate Logrotation erforderlich; externe Sicherung/Export regelmäßig vorsehen.

Verbindlicher Ablauf und Benchmark-Gate: [Staging](staging.md). Tests unter Linux benötigen ein persistentes lokales Dateisystem; standardmäßig /var/tmp, alternativ OTAM_TEST_TMPDIR auf passendem Datenträger. Nicht tmpfs als Teststaging freigeben.
