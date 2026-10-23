# LP Archiv: Ergebnis und Laufzeitauswertung nach Band 2

Ausgewertet am 22.10.2026 anhand vorhandener SQLite-Zustände, 46.766 Ereignisse
und Kerneljournal. Keine erneute physische Bandprüfung, kein Benchmark und keine
Änderung an Quellen, Medien oder laufender Installation. Zeiten Europe/Berlin,
Durchsätze dezimale MB/s.

## Ergebnis

Der Gesamtjob `038ba84f-1596-4829-89d8-c2089b023811` ist VERIFIED: zwei Medien,
17 TARs, 30.800 Dateien und 1.522.565.501.226 Nutzbytes. Beide Queueaufträge sind
SUCCEEDED, sämtliche 17 Archiv-/Verifikationsdatensätze sind VERIFIED und alle
Staging-Cleanups COMPLETE. Keine ERROR-/WARNING-Ereignisse in den beiden Kindjobs.
Das ist der Nachweis der vollständigen Archiv-/Datei-/Receipt-Prüfung, keine neue
separate Wiederherstellungsprobe.

Band 2 lief vom 21.10.2026 17:24:19 bis 22.10.2026 03:10:42. Gegenüber Band 1
mit ähnlich großer Datenmenge sank die Laufzeit von 16 h 24 min 43 s auf
9 h 46 min 23 s: 6 h 38 min 21 s bzw. 40,45 % weniger. Das ist kein kontrollierter
Benchmark: unterschiedliche Dateiverteilung und Medien, sechs gegenüber elf
TARs sowie verschiedene Verifikationsabläufe. Der Vergleich belegt die tatsächliche
Verbesserung dieses Jobs, keine allgemeine Beschleunigungsgarantie.

Die kanonischen Hashes des ersten Kindjobdatensatzes und aller sechs zugehörigen
Archivdatensätze stimmen exakt mit dem Snapshot vor dem Start von Band 2 überein.
Damit sind unveränderte Katalogdaten belegt; Band 1 wurde dafür nicht erneut
physisch gelesen. Signierter Katalogsync zuletzt UNCHANGED auf Sequenz 233.

## Zeitanteile

| Anteil | Band 1, 0.7.3 / archivweise | Band 2, 0.8.2 / Batch |
| --- | ---: | ---: |
| TAR-Daten | 762,389 GB | 760,239 GB |
| Gesamtdauer des Queueauftrags | 16 h 25 min | 9 h 46 min |
| TAR-Erstellung/STAGING | 2 h 34 min, enthält alte lokale Inhaltsprüfung | 1 h 33 min |
| VALIDATION-Ereignisintervalle | 3 h 12 min, weitere Prüfungen lagen auch außerhalb dieser Phase | 2 h 12 min, beide vollständigen lokalen Prüfpässe |
| Schreibstreams, aus finalen Byte-/Ratenwerten | 1 h 51 min | 1 h 53 min |
| Rücklese-/Prüfstreams, aus finalen Byte-/Ratenwerten | 4 h 00 min | 3 h 59 min |
| Mittlere Schreibrate | 114,51 MB/s | 112,07 MB/s |
| Mittlere kombinierte Rücklese-/Prüfrate | 52,86 MB/s | 52,97 MB/s |

Für Band 2 decken TAR-Erstellung, beide lokalen Prüfpässe, Schreib- und
Rücklesestreams etwa 9 h 37 min ab; rund neun Minuten bleiben für Vorprüfung,
Übergänge, Steuerung, Belege, Abschluss und übrige Lücken. Die Schreibfolge
einschließlich Zwischenräumen dauerte etwa 1 h 59 min; der Übergang zum ersten
Readback etwa 2 min 35 s. Kein gezählter interner mechanischer Spulvorgang.

Das Zusammenführen/Entfernen lokaler Wiederholungsprüfungen und der Batchablauf
verkürzen den Gesamtjob deutlich. Die physische Rücklese-/Prüfrate selbst hat
sich dagegen praktisch nicht verbessert. Die aus RAM gemessenen 196–218 MB/s
dürfen ausdrücklich nicht als Banddurchsatz angegeben werden.

## Verbleibender Rückleseengpass

Die neuen Zähler direkt am synchronen Reader ergeben über elf TARs:

- 6.791 s / 1 h 53 min innerhalb von `os.read`, einschließlich Treiber-/Kernelarbeit
  und Warten; bezogen auf die Nutzdaten entspricht das etwa 111,95 MB/s.
- 7.560 s / 2 h 06 min übrige verstrichene Readerzeit: unter anderem Hashing,
  TAR-/Dateiverarbeitung, Kopien, Laufzeitverwaltung, Fortschritts-DB und Scheduling.
  Das ist keine isolierte CPU-Zeitmessung und keine bewiesene SQLite-Schuld.
- Zusammen 14.352 s / 3 h 59 min und etwa 52,97 MB/s. Geräte-Reads und übrige
  Verarbeitung erfolgen im synchronen Ablauf nacheinander.
- Etwa 1,45 Millionen Geräte-Leseaufrufe, im Mittel annähernd 512 KiB je Aufruf
  einschließlich EOF-Aufrufen. Der frühere RAM-memfd-Test lieferte dagegen
  1-MiB-Blöcke ohne Gerätewartezeit.

Ein bloßes Abschalten des alten Python-Prefetchers ist damit kein abschließender
Leistungsnachweis. Der RAM-Test isolierte zwar dessen erhebliche Kosten, bildete
aber nicht den möglichen Gewinn durch überlappende Gerätewartezeit und Prüfung
ab. Ein künftiger Kandidat muss genau diesen Zielkonflikt messen. Geeignet sind
zunächst Softwareadapter mit realistischen 512-KiB-Records und reproduzierbarer
Latenz, dann höchstens ein gezielter notwendiger Hardware-Nachweis. Native bzw.
separate Prozesspufferung und weniger Kopien sind Kandidaten, keine bereits
freigegebenen Lösungen. Erste-Filemark-Latch, exklusive Gerätesperre, Ende des
Readers vor jeder Positionierung und vollständige TAR-/Datei-/Receipt-Prüfung
müssen unverändert bewiesen werden.

Bei idealer Überlappung der gemessenen Anteile wäre deren Maximum statt Summe
maßgeblich, theoretisch etwa 2 h 06 min statt 3 h 59 min für den Readback.
Die daraus ableitbaren knapp zwei Stunden sind eine idealisierte Obergrenze
des Einsparpotenzials, keine gemessene oder zugesagte künftige Laufzeit.

## Schreibversorgung und Unterbrechungen

Zehn TARs wurden mit mittleren Raten um 112–116 MB/s geschrieben; das erste
erreichte nur 93,07 MB/s. In dessen Fortschrittsmeldungen liegt eine Lücke von
112,89 s ab etwa 21:14:03. Vor und nach der Lücke war als letzter Pufferfüllstand
100 % gemeldet. Das legt keine fehlende Datenbereitstellung aus dem Staging nahe,
beweist aber auch keine konkrete Laufwerks-/Reinigungsursache.

Für alle elf Schreibstreams liegt der Median der gemeldeten Pufferfüllstände
bei 100 %. Sämtliche Werte unter 10 % treten erst ab mindestens 99,71 % des
jeweiligen TARs auf. Der Endablauf darf daher nicht pauschal als Unterversorgung
gewertet werden. Dies sind gespeicherte mbuffer-Samples; interne Bandbewegungen
und Liveness jeder einzelnen Statuslogzeile wurden nicht unabhängig gemessen.
Ein größerer Schreibpuffer oder höheres Hostlimit ist deshalb derzeit nicht die
begründete erste Maßnahme.

## USB-Quellpfad und Reinigung

Der Kernel protokollierte fünf UAS-Geräteresets mit Lesefehlern auf `sdc`:
17:28:40, 18:00:35, 18:56:24, 19:28:55 und 19:58:04 am 21.10.2026.
`/mnt/USB` ist `/dev/sdc1` / ext4. Alle Vorfälle lagen vor dem ersten Write um
21:09:29, während der lokalen Vorbereitung; sie erklären nicht die spätere
Readbackrate. OTAM erhielt daraus keinen Jobfehler, und die Daten bestanden
die vollständigen SHA-Prüfungen gegen den Plan. Trotzdem ist dieser Quellpfad
auffällig. Vor weiteren großen Quellleseläufen Kabel, USB-SATA-Adapter,
Stromversorgung und Datenträgerzustand gezielt untersuchen. Keine ungeprüfte
Treiberumstellung oder destruktive Reparatur aus dieser Auswertung ableiten.

Die vom Nutzer beobachtete C-Reinigungsaufforderung bleibt ebenfalls offen.
Der Nutzer wartet auf das Reinigungsband und möchte nach Jobende reinigen.
Der Archivjob ist nun abgeschlossen; vor weiteren großen Bandjobs reinigen,
sobald das geeignete Reinigungsband vorliegt. Kein Beleg, dass Verschmutzung
allein die Rückleserate oder die Schreibpause verursacht hat.

## Weitere Optimierungen und Messgrenzen

1. Priorität: Lesen und Prüfen effizient überlappen und Kopieraufwand messen.
   Vollständige Integritätsprüfung beibehalten; keine Stichproben als Ersatz.
2. Hashes bereits beim TAR-Erzeugen berechnen und dadurch einen der zwei lokalen
   Vollpässe vermeiden, sofern eine unabhängige vollständige Vorprüfung und
   belastbare Veröffentlichung erhalten bleiben. Das ist ein neu zu prüfender
   Entwurf; der zusätzliche CPU-Aufwand beim Erzeugen kann einen Teil des
   I/O-Gewinns aufzehren. Kein einfaches Abschalten einer Prüfung.
3. Für den nächsten regulären Lauf tatsächliche Prozess-/Thread-CPUzeit,
   Prüfer-/Kopierkosten, Callback-/Commitzeit und CPU-Takt erfassen. Aktuell ist
   `schedutil` eingestellt; historische Taktwerte während des Jobs liegen nicht
   vor. Eine konkrete Taktregelungsursache ist damit nicht bewiesen.

Der Worker war seit 21.10.17:17 aktiv. Nach dem Job meldete systemd etwa
6 h 19 min kumulierte CPUzeit und 5,64 GB MemoryPeak; darin enthalten sind
Hintergrundarbeit sowie Dateicache/Kindprozesse, keine isolierte Job- oder reine
Prozess-RAM-Messung. IOAccounting war deaktiviert, daher gibt es keine belastbare
systemd-Read-/Write-Bytebilanz für diesen Lauf. Logische Prüfbytes sind nicht
gleich physische HDD-Bytes wegen des Caches.

Rohereignisse, Analyse-JSON, gefiltertes Kerneljournal, Accounting und
Metadatenvergleich liegen ausschließlich lokal ignoriert unter
`docs/hardware/testdaten-2026-10-19/lp-performance-20261022/` mit SHA256SUMS.
