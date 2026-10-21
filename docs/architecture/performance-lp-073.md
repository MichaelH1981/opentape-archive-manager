# Laufzeitdiagnose LP Archiv unter 0.7.3

## Ergänzung: CPU-Messung nach Installation von 0.8.0

Am 21.10.2026 im bestätigten Leerlauf ohne Band-, Quell- oder Stagingzugriff
gemessen (Celeron J4005, OpenSSL 3.5.7, dezimale MB/s):

| RAM-Prüfung | MB/s Nutzdaten |
| --- | ---: |
| Ein SHA-256, ein Thread | 664,5 |
| Zwei SHA-256 pro Nutzbyte, ein Thread | 331,7 |
| Echter `inspect_stream`, TAR und Archiv-/Dateihashes, BytesIO | 220,5 |
| Derselbe Prüfer mit `TapeRecordReader` über RAM-memfd | 205,8 |
| Zusätzlich installierter PrefetchReader mit 16 MiB Queue | 91,3 |

Kurze synthetische 64-MiB-Eindatei-TARs begrenzen die Aussage: Dies ist keine
Messung des Bandes oder der mechanischen Bewegungen. SHA allein erklärt die
historischen 51–56 MB/s nicht. Die Kombination von Vorlesethread, Kopien und
Prüfer zeigt auf dieser CPU erheblichen zusätzlichen Aufwand; der neue Puffer
ist damit kein belegter Geschwindigkeitsgewinn. Ein separater reiner Kopiertest
erreichte 723 MB/s, ein ausschließlich im Testprozess veränderter Direktlesepfad
1244 MB/s. Das isoliert den Engpass bei gleichzeitigem Parsen/Hashen noch nicht.
Der Prototyp wurde nicht installiert. Vor Fortsetzung mit Band 2 muss diese
Interaktion weiter geklärt werden; kein zusätzlicher großer Bandtest dafür.
Rohmesswerte liegen ausschließlich im ignorierten Hardwaredossier.

Nachtrag zur Korrektur 0.8.1: Der zusätzliche Python-Vorlesethread wird nicht mehr
im regulären `LinuxTape.open_read` verwendet. Der bereits bewährte synchrone
`TapeRecordReader` und sein 1-MiB-Streambuffer bleiben erhalten. Ein anschließender
RAM-Testprozess ohne Vorlesethread erreichte in vier aufeinanderfolgenden Fenstern
196,2 / 217,8 / 217,8 / 217,5 MB/s für die vollständige TAR-/SHA-Prüfung; der aktive
Kern lag bei etwa 2,7 GHz. Das grenzt einen unvermeidbaren SHA-CPU-Flaschenhals bei
51–56 MB/s weiter ein, ersetzt aber keine Messung des tatsächlichen Bandstroms.
In gemischten Testprozessen lag der synchrone Pfad zeitweise nur bei 120 MB/s;
eine allgemeine garantierte Rate wird daraus nicht abgeleitet. Das Zusammenspiel
des Vorlesethreads mit der Verarbeitung bleibt eine Leistungsgrenze dieser
Implementierung, kein Nachweis eines bestimmten mechanischen Laufwerksfehlers.

Neue Telemetrie misst Bytes, Aufrufzahl und Zeit innerhalb der Geräte-Reads sowie
die gesamte Reader-Laufzeit. Sie benötigt keine zusätzlichen Datenlesepässe und
hilft beim nächsten regulären Medium, Geräte-/Treiberwartezeit von übriger
Verarbeitung zu unterscheiden. Keine Änderung an SHA-, TAR-, Filemark- oder
Receipt-Prüfungen; keine Änderung des Live-Verifikationsmodus.

Stand 21.10.2026, nach Abschluss des ersten Mediums. Bestehende SQLite-Ereignisse
wurden ausschließlich lesend ausgewertet; keine zusätzlichen Bandläufe oder
Benchmarks. Erstes Kind `06e49af7-7816-49dc-8461-eab95818b08c` ist VERIFIED,
der Gesamtjob `038ba84f-1596-4829-89d8-c2089b023811` WAITING_MEDIA. Alle sechs TARs
enthalten zusammen 762.388.561.920 tatsächlich geschriebene TARbytes.

## Beobachtete Zeitbilanz

Ab Bestätigung des ersten Medienauftrags bis Abschluss etwa 16,4 Stunden;
die vorausgegangene Quelleninventarisierung/Hashplanung ist darin nicht enthalten.

| Arbeit | Ungefähre Zeit | Herleitung und Grenze |
| --- | ---: | --- |
| Bandschreibphase | 1,86 h | Zeit zwischen TAPE_WRITE und TAPE_READBACK; inklusive kleiner Steuerungsanteile |
| Eigentliche Rücklese-/Prüfpässe | 4,01 h | Summe aus Endbytezahl / gemeldeter mittlerer Rate je TAR; Parser und SHA-Prüfung laufen bereits im selben Lesepass |
| Lokale Vorbereitung, wiederholte Prüfungen und übriger Ablauf | 10,5 h | Differenz; enthält auch Positionierung, Receipts und Abschlussarbeiten, daher nicht ausschließlich HDD-/CPU-Zeit |

Die Phasenbezeichnungen allein würden täuschen: STAGING umfasst rund 2,57 h
einschließlich einer lokalen Inhaltsprüfung innerhalb `create_archive`;
VALIDATION rund 3,21 h; READY bis Schreibbeginn rund 2,14 h für erneute
Vollprüfungen. TAPE_READBACK umfasst rund 6,62 h für alle sechs TARs; darin
liegen zusätzlich zur eigentlichen Bandrücklesung erneute lokale Prüfungen und
Receiptabschluss. Kein Rückschluss von dieser Phasendauer auf reine Bandlaufzeit.

Schreibdurchsatz je TAR etwa 113–117 MB/s; mittlere vollständige Rücklese-/
Prüfraten etwa 51–56 MB/s. Frühere Stichproben lokaler Vollprüfungen lagen um
185–193 MB/s HDD-Leserate. Eine Worker-CPU-Stichprobe während Rücklesung lag bei
70 % eines Kerns; dies beweist keinen alleinigen CPU-Engpass. Interne mechanische
Rückpositionierungen wurden nicht gemessen. Ein früherer USB-Quellplattenreset
bleibt ein separater Befund und erklärt nicht die belegten wiederholten lokalen
Vollprüfungen. Für das erste Medium wurden keine Jobfehler gemeldet.

## Belegter Codepfad: acht lokale Lesepässe je neuem TAR

Für den hier verwendeten archivweisen Modus und neu erstelltes Staging:

1. `archive.create_archive` schreibt das TAR und ruft anschließend `verify_archive` auf: ein praktisch vollständiger lokaler Inhaltslesepass.
2. `StagingStore.prepare` liest das TAR anschließend separat für `sha256`, erneut für `verify_archive` und nochmals für `sha256`: drei weitere Pässe.
3. `ArchiveService.backup` ruft unmittelbar vor Schreiben `validate_ready` auf: ein separater Archivhash-Pass und ein TAR-/Datei-Prüfpass.
4. Nach physischer Rücklesung ruft `backup` nochmals `validate_ready` auf: wieder zwei lokale Pässe.

Das sind acht praktisch vollständige lokale Nutzdatenlesepässe, bei diesem Medium
etwa 6,1 TB zusätzliche lokale Lesemenge. Hinzu kommen das Lesen der Quelle für
die TAR-Erstellung, HDD-Schreiben, das Lesen des TARs für den Bandwriter und die
physische Bandrücklesung. Die gezählten Aufrufe sind belegt; genaue physische
HDD-Bytes hängen unter anderem vom Cache ab. Keine Behauptung, alle acht Pässe
seien ohne Ersatzmaßnahmen ersatzlos entfernbar.

`verify_stream` berechnet bereits Archiv-SHA-256, prüft Manifest/TAR und
Datei-SHA-256 während desselben physischen Lesestroms. Der gegenwärtige Prozess
liest das Band nicht erst komplett auf Platte, um danach separat SHA zu rechnen.
Die zusätzliche Arbeit erfolgt am lokalen Staging. Ein neuer RAM-Puffer dient
der Entkopplung von Reader und Prüfer, nicht der erstmaligen Einführung von
On-the-fly-Verifikation. Bei dauerhaft langsamem Prüfer genügt ein endlicher
Puffer nicht; dessen tatsächliche Kosten müssen separat gemessen werden.

## Prioritäten für den 0.8-Kandidaten

- Lokale Archivhash-, TAR- und Dateiprüfung in einem Lesepass zusammenführen. Verantwortlichkeiten von Erzeugung, Staging-Publikation und Service-Vorprüfung bereinigen, sodass dieselbe vollständige Prüfung nicht unbeabsichtigt mehrfach läuft.
- Für jede entfallende Wiederholungsprüfung dokumentieren, welcher Nachweis sie ersetzt: unveränderte Dateiidentität/Fingerprints, geschützte Veröffentlichung und Deskriptorbindung, vollständige lokale Vorvalidierung, Hash des tatsächlich geschriebenen Streams und physischer Readback gegen den geprüften Originalhash. Geänderte oder nach Prozessverlust unklare Artefakte müssen weiter vollständig geprüft werden. Keine bloße Abschaltung von Sicherheitsprüfungen zur Laufzeitverkürzung.
- Den belegten doppelten SHA- und TAR-Lesepass in `validate_ready` zuerst zu einer kombinierten Prüfung machen; die Entscheidung über weitere eingesparte Pässe separat testen. Lokale Prüfdauer vor/nach Bandarbeit im UI sichtbar machen.
- Rücklesepuffer und CPU-/Parser-/Hash-/SQLite-Profiling getrennt prüfen. Bereits vorhanden ist ein 1-MiB-TAR-Streambuffer; ein vermeintlicher unveränderter 10-KiB-Standardbuffer ist daher keine belegte Ursache im OTAM-Pfad.
- Batchangebot reduziert Wechsel zwischen Schreiben und Rücklesen, entfernt aber nicht von sich aus lokale redundante Validierungen oder einen dauerhaft langsamen Prüfer.
- Tests müssen gelesene Bytes und Anzahl voller Pässe je Workflow messen sowie Quellenänderung, lokale Korruption, Austausch, Rechteänderung, Prozessverlust, EOM und falsches Readback weiter ablehnen. Performanceziele erst nach Vergleichsmessung bestätigen; keine feste Gesamtzeit oder Beschleunigung zusagen.

Es wurde kein Code installiert oder am bestehenden Plan geändert. Am erreichten
Medienwechsel ist ein Update erst mit implementiertem, geprüftem und zu diesem
Plan kompatiblem Kandidaten zulässig; dieser lag bei der Diagnose noch nicht vor.
