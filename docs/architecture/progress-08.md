# Vorbereitung 0.8: Fortschritt von Planung bis Verifikation

Stand 20.10.2026: vorbereiteter Umsetzungsentwurf, noch nicht implementiert oder
installiert. Der laufende Produktivjob und die Serverinstallation bleiben
unverändert. Ein 0.8-Kandidat darf lokal entwickelt und softwaregetestet werden;
Installation erst nach Jobende, Prüfung offener Queue-/Staging-/Medienzustände
und Sicherung der Datenbanken. Kein Wechsel des Codes unter einem laufenden Job.

## Ausgangspunkt im Code

- `archive.inventory` kennt nach dem Quellenplan Dateifingerprints, Dateizahl und Nutzbytes. `digest` liefert bislang keinen Zwischenstand innerhalb einer großen Datei. Metadatenentdeckung kennt die endgültige Menge erst nach Abschluss.
- `source_plans` markiert `HASHING`, meldet bislang aber keinen laufenden Bytefortschritt. Ein Bindungsauftrag kann anschließend einen Einband- oder Mehrbandplan erzeugen; der Quellenjob muss währenddessen sichtbar bleiben.
- `StagingStore.prepare` aktualisiert `progress_bytes` während der TAR-Erstellung etwa sekündlich. Anschließende lokale Hash-/TAR-/Fingerabdruckprüfungen sind zusätzliche Arbeit und müssen eigene Phasen erhalten.
- `ArchiveService._monitor` und LinuxTape liefern Transferfortschritt für Schreiben und Rücklesung. Diese Zähler sind wiederzuverwenden; nicht durch neue Probe-I/O ersetzen.
- Jobdetails rendern bereits Balken aus `staged_archives`, aber Jobübersichten enthalten keine einheitliche Fortschrittsspalte. Das fünfsekündige Polling aktualisiert aktuell keine geöffneten Modaldetails. Unterschiedliche Phasen verwenden teils unterschiedliche Bytebezüge.

## Verbindliche Darstellung

| Phase | Messgröße und Anzeige | Bedeutung von 100 % |
| --- | --- | --- |
| Quellen erfassen | Aktivitätsbalken; gefundene Dateien und Nutzbytes, verstrichene Zeit | Inventar abgeschlossen; vorher keine bekannte Gesamtmenge |
| Quelle erneut prüfen | Geprüfte Dateifingerprints / geplante Dateizahl | Metadatenprüfung abgeschlossen, keine Inhaltshashes behauptet |
| Prüfsummen berechnen | Tatsächlich gelesene Nutzbytes / versiegelte Nutzbytes; Dateien abgeschlossen / gesamt | Alle Hashes und Quellenänderungsprüfungen abgeschlossen |
| TAR erstellen | Eingelesene Quelldaten / Nutzdaten des TARs; TAR- und Kindjob-Zähler | Kopierphase beendet; lokale Validierung folgt |
| Staging validieren | Eigene Fortschritte für TAR-Hash und Inhaltsprüfung, jeweils klar benannte Bezugsgröße | Alle lokalen Prüfungen und sichere Veröffentlichung abgeschlossen; Status READY |
| Medium prüfen / positionieren | Aktivitätsanzeige mit aktuellem Arbeitsschritt; gegebenenfalls geprüfte Receipts / erwartete Receipts | Geräte-/Receiptprüfungen abgeschlossen, keine Nutzdatenprüfung übersprungener Archive behauptet |
| Band schreiben | Tatsächlich an den Writer übergebene Bytes / TARbytes | Byteübertragung beendet; Close/Flush/Filemark und Receipt sind getrennte Schritte |
| Band zurücklesen / verifizieren | Tatsächlich zurückgelesene Bytes / erwartete TARbytes | Lesepass beendet; Hash-, Manifest-, Datei- und Receiptprüfungen müssen noch erfolgreich abschließen |
| Medium wechseln | Erwartetes Medium und abgeschlossene / geplante Medien | Kein zeitlicher Prozentwert; ausdrückliche Bestätigung bleibt nötig |

Bei `verify_mode=media` Schreib- und Verifikationsfortschritt getrennt über alle
TARs des aktuellen Mediums aggregieren. Bei archivweiser Verifikation Reihenfolge
je TAR zeigen. Phasenwechsel darf den Phasenbalken zurücksetzen, muss aber den
neuen Bezug klar benennen. Keine künstlich gewichtete Gesamtjob-Prozentzahl:
Positionierungen und Medienwechsel besitzen keine belastbare Dauer. Eine
Schrittliste zeigt bereits fertige, laufende und noch offene Schritte.

Nullbyte-Dateien und leere Bytephasen brauchen Dateizähler bzw. einen ausdrücklich
abgeschlossenen Phasenstatus, keine Division durch null. Bytefortschritt und
Integritätsstatus sind getrennte Felder. Fehlgeschlagene Hashprüfung bleibt ein
Fehler, auch wenn zuvor sämtliche Bytes gelesen wurden.

## Daten- und Aktualisierungspfad

1. Einen gemeinsamen optionalen Fortschrittscallback für Inventar-/Hash- und Validierungsroutinen einführen. Nur vorhandene I/O-Schleifen instrumentieren; Deskriptor-, Fingerprint-, O_NOFOLLOW- und Integritätsprüfungen unverändert beibehalten. Auch große Einzeldateien müssen Zwischenstände liefern.
2. Versionierte Snapshots mit Job-/Kindjob-/Archivbezug, Versuch, Phase, Einheit, erledigt/gesamt (gesamt darf unbekannt sein), Datei-/TAR-Zählern, Zeitstempel und Phasenstatus persistieren. Nicht in versiegelte Plan-/Manifestdaten schreiben. Bei Neustart einen neuen Versuch beginnen; alten Fortschritt als unterbrochen erhalten.
3. Updates höchstens ungefähr einmal pro Sekunde persistieren; Start, Phasenwechsel und Ende sofort. Letzten Snapshot pro laufendem Bezug aktualisieren statt das Ereignislog pro Block zu vergrößern. Normale Abschluss-/Fehlerereignisse bleiben erhalten. Alte Kataloge brauchen sichere Migration; lesender Katalogbetrieb muss fehlende Snapshots tolerieren.
4. API liefert dieselben Snapshots für Übersicht und Details; Eltern aggregieren ihre Kindjobs ohne doppelte Zählung. Fortschrittszugriffe dürfen weder Dateilisten vollständig serialisieren noch Bandgeräte öffnen. Snapshot-Replikation behält ihre klare Standzeit und wird nicht als Livefortschritt dargestellt.
5. Frontend aktualisiert Fortschrittsbereiche gezielt, auch bei geöffneten Jobdetails. Keine Formulare, Medienauswahl, Fokus oder Scrollposition durch vollständiges Neuaufbauen verlieren. Sichtbare Zahlen, barrierefreie Progressbar und DE/EN-Texte vorsehen; Prozent nur bei bekannter Bezugsgröße.
6. Durchsatz und ETA aus einem geglätteten Messfenster pro Phase/Versuch ableiten. Anlauf, Stillstand, zu alte Daten und Verbindungsabbruch ergeben „Restzeit unbekannt“ bzw. „letzter Stand …“. Warten und Positionieren nicht in eine fortlaufende I/O-Rate einrechnen. ETA ist eine Schätzung, kein zugesagter Endzeitpunkt.

## Abnahmekriterien für den Kandidaten

- Eine große Einzeldatei liefert Zwischenstände vor Dateiende; zahlreiche kleine Dateien überlasten SQLite oder Ereignislog nicht. Callback-Zähler stimmen mit tatsächlich gelesenen Bytes überein, ohne zusätzliche Reads.
- Planung, Ein-/Mehrbandbindung, Staging-Erstellung, erneute lokale Validierung, Schreiben und beide Rücklesemodi zeigen die richtige Bezugsgröße. Eltern-/Kind-/TAR-Aggregation zählt nichts doppelt.
- Quellenänderung, kaputtes TAR, Hash-/Receiptfehler, EOM, Prozessverlust und Wiederaufnahme erzeugen keinen falschen Erfolgsstatus. Fortschrittsupdates lockern keine Sperre und starten keinen automatischen Retry.
- Keine 0/0-, NaN- oder über-100-%-Anzeige. Unbekannte Summen, Nullbyte-Dateien, Skip bereits gültiger TARs, Phasenwechsel und neue Versuche sind definiert.
- Dashboard, Jobliste, Staging und geöffnete Details aktualisieren sich, ohne Eingaben zu verlieren. Prozent, Bytes, Dateizahl, Phase und Datenalter sind auch mobil und per Screenreader verständlich.
- Migration, alter Katalogsnapshot, Datenbankfehler, stale Updates und verlorene Verbindung sind softwaregetestet. Erst nach Ende des jetzigen Jobs Installation planen; keine redundanten großen Bandtests für die UI.
