# Alternativenanalyse

Recherche: 2026-10-17, öffentliche Primärquellen. Keine lokalen Installationen oder Tape-Benchmarks. „Unterstützt LTO-4“ bedeutet generisches Linux-SCSI-Tape, keine bestätigte Abnahme des ULT3580-HH4 mit diesem Controller. Featuretabellen ersetzen keine Restore-Tests.

| Projekt | Wartung / Lizenz | LTO-4 / Mehrband | Katalog / Restore / Integrität | Bewertung |
|---|---|---|---|---|
| STFS | Öffentliches Go-Projekt, Releases vorhanden; AGPL-3.0. Kleine Community; langfristige Zusagen nicht belegt | Linux-Tapegeräte dokumentiert; automatisches Mehrbandmanagement für diesen Auftrag nicht belegt | SQLite-Index, TAR, Restore, optionale Signaturen/Verschlüsselung. Vollständige Rücklesung als zwingendes Commit-Gate nicht belegt | Technisch nahe; vor einer Übernahme wären Append-/Crash-/EOM-Abnahme und Lizenzentscheidung nötig |
| Bareos | Aktiv: 25.0.4 im Juli 2026; AGPLv3 | Tape Storage und Pools/Volumes; generisches SCSI-LTO | Umfassender Dateikatalog, Restore, VolumeToCatalog liest Medien erneut; Digest-/Verify-Semantik muss separat geprüft werden | Stärkste fertige Alternative; mehr Dienste/Konfiguration und eigenes offenes Backupformat statt einfacher TAR-Dateien |
| Bacula Community | Community 15.0.3 angekündigt 2025; AGPLv3 überwiegend, Ausnahmen prüfen | Tape, Volume-Pools, Recycling/Retention | Dateikatalog, Restore/bscan und Verify; konkrete Community-Version und Verify-Digests abnehmen, Enterprise-Funktionen nicht unterstellen | Bewährt, aber komplexer Betrieb und nicht direkt TAR-lesbare Medien |
| GNU tar | Langjährig gepflegt, Manual 1.35; GPLv3+ | Tape-Dateien, Mehrvolumen möglich | Kein zentraler Dateikatalog/Medieninventar. Compare allein ist keine SHA-256-Rücklesegarantie | Offenes Austausch-/Recoveryformat; Mehrvolumen/Splits für OTAM deaktivieren |
| mt-st | Öffentliches Linux-Projekt mit Changelog und laufenden Änderungen; COPYING enthält GNU GPL (exakte Paketlizenz bei Installation prüfen) | Linux SCSI-Tape, explizit LTO-4-Densitycode | Positionierung und Status, kein Dateikatalog/Datei-Hash | Geplante Steuerungsschicht, keine implizite Identitätsgarantie |
| mbuffer | Upstream nennt 20260926 als neueste Version; 20260929 ausdrücklich zurückgezogen. GNU GPL 3 | Puffert Streams; Mehrvolumen und Tape-aware-Modus vorhanden | Kein Katalog/Restore-Index. Streamhash ersetzt nicht Dateiprüfung nach Rücklesung | Geplante Pufferung, kein automatischer Medienwechsel; zurückgezogene Version vermeiden |

## Entscheidung
Bareos kann wesentliche Backupanforderungen bereits erfüllen und sollte bei primärem Fokus auf rotierende Systemsicherungen bevorzugt erprobt werden. Für den hier geforderten kleinen privaten Dateiarchivdienst mit SQLite, unabhängiger TAR-Wiederherstellung und einem zwingenden Rücklese-Commit wird ein eng begrenzter OTAM-Orchestrator gebaut. Eigenentwicklung beschränkt sich auf Katalog, Planung, sichere Abläufe, Manifeste und Bedienung; Treiber und Bandsteuerung bleiben etablierte Linux-Komponenten. Keine STFS-/Bareos-/Bacula-Quellen übernommen. Entscheidung ist vor Hardware-Write anhand von Testaufwand und Zuverlässigkeit erneut zu prüfen. Bei Scheitern der Positionierungsabnahme bleibt Bareos die Rückfalloption.

## Quellen
- [STFS README, Lizenz und Funktionen](https://github.com/pojntfx/stfs), [Releases](https://github.com/pojntfx/stfs/releases)
- [Bareos Lizenz/Community](https://www.bareos.com/faq/), [25.0.4](https://www.bareos.com/bareos-25-0-4/), [Verify](https://download.bareos.org/current/BareosMainReference/Appendix/VerifyFileIntegrityWithBareos.html), [Director/VolumeToCatalog](https://download.bareos.org/current/BareosMainReference/Configuration/Director.html)
- [Bacula Lizenzen](https://www.bacula.org/what-is-bacula/bacula-copyright-trademark-and-licenses/), [Community-News](https://www.bacula.org/), [Utility-Handbuch bscan/btape](https://www.bacula.org/11.0.x-manuals/en/utility/utility.pdf)
- [GNU tar Manual](https://www.gnu.org/software/tar/manual/tar.html), [Tape files](https://www.gnu.org/software/tar/manual/html_node/Tape-Files.html)
- [mt-st](https://github.com/iustin/mt-st), [Changelog](https://github.com/iustin/mt-st/blob/main/CHANGELOG.md), [Linux st-Treiber](https://www.kernel.org/doc/html/v6.6/scsi/st.html)
- [mbuffer Upstream, Lizenz und Rückzugshinweis](https://www.maier-komor.de/mbuffer.html)
