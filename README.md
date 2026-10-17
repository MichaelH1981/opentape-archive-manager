# OpenTape Archive Manager (OTAM)

Offener, sicherheitsorientierter Archivierungskern für private Linux-Bandarchive. **Phase-1-Preview mit persistentem Bandsimulator; noch keine produktive LTO-Software.** Reale Bandschreibzugriffe sind gesperrt. Weboberfläche und systemd-Dienst folgen in Phase 3.

[Projektübersicht und Funktionsstand](docs/project-overview.md)

Implementiert: lesende Linux-Erkennung, SQLite-Katalog, SHA-256-Inventar und bestätigte Archivplanung, persistentes lokales Staging mit Wiederaufnahme, PAX-TAR mit selbstbeschreibendem Manifest, Append mit Medien-ID und Prozesssperre, vollständige Rücklesung vor VERIFIED, sichere selektive Wiederherstellung, Suche/Exporte, Neustartbehandlung und Katalogrekonstruktion. Keine automatische Quelllöschung oder Medienwiederverwendung. MIT-Lizenz.

```bash
python3 -m otam --help
python3 -m otam doctor
python3 -m unittest discover -v
```

Python >=3.11, keine Laufzeitabhängigkeiten außerhalb der Standardbibliothek. Einstieg in den vollständigen Testzyklus: [Bedienungsanleitung](docs/usage.md).

- [Architektur](docs/architecture/overview.md), [Alternativen](docs/architecture/alternatives.md), [Risiken](docs/architecture/risks.md), [Entwicklungsplan](docs/architecture/plan.md)
- [Hardware-Abnahme und lokale Diagnoseberichte](docs/hardware/README.md)
- [Installation](docs/installation.md), [Konfiguration](docs/configuration.md), [Datenbankschema](docs/database.md), [Bandformat](docs/tape-format.md), [verbindliches Staging](docs/staging.md)
- [Disaster Recovery ohne Datenbank](docs/disaster-recovery.md), [Wiederherstellung ohne OTAM](docs/recovery-without-otam.md)
- [Entwicklung](docs/development.md), [Test- und Abnahmeplan](docs/testing.md)

Die vorhandenen Server-Skripte wurden über SSH ausschließlich gelesen und bleiben unverändert. SSD-/NAS-Befunde sprechen für vollständiges SSD-Staging vor dem Bandstream. Das tatsächliche Filemark-/EOD-/EOM-Verhalten des IBM ULT3580-HH4 muss mit ausdrücklich freigegebenem Testmedium validiert werden. Softwaretests ersetzen diese Hardwareabnahme nicht. V1 archiviert reguläre Dateien; ACLs/xattrs/Links/leere Verzeichnisse und vollständige Systemstände sind noch nicht enthalten.

Staging-TARs werden erst nach vollständiger Rückleseverifikation entfernt. `stage`, `staging-status` und `staging-benchmark` ergänzen die CLI; ein bestandener Simulatorjob ist weder Hardware- noch 120-MB/s-Leistungsfreigabe.
