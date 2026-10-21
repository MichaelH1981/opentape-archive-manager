# Laufzeitdiagnose LP Archiv unter 0.7.3

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
