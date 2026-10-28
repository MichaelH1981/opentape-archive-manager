# CPU- und Pufferübersicht – 0.8.8

In Version 0.8.8 enthalten; am 28.10.2026 nach vollständig verifiziertem ersten
Medium und vor Beginn des zweiten Mediums installiert. Die Übersicht zeigt Worker-CPU, gesamte Host-CPU, I/O-Warteanteil
und den zum aktuellen TAR gehörenden Lese- bzw. Schreibpuffer. Jobdetails zeigen
dieselben vorhandenen Transferpufferwerte.

## Begrenzter Aufwand

- Der vorhandene Heartbeat sammelt alle fünf Sekunden Prozess-CPU-Zeit und eine
  aggregierte Zeile aus `/proc/stat`. Keine Prozesse auflisten, keine Subprozesse,
  keine Benchmarks, keine Hardware-/SCSI-Abfragen.
- Der Sampler hält nur zwei Zählerstände. Eine kleine Statuszeile wird überschrieben;
  es entsteht keine zusätzliche Messhistorie.
- Heartbeat und CPU-Status werden gemeinsam in der bisherigen Heartbeat-Transaktion
  gespeichert. Keine zusätzliche Commit-/fsync-Frequenz.
- HTTP liefert nur diesen Cache. Weitere offene Browser starten keine Messungen.
- Die Pufferanzeige übernimmt bestehende `io_progress`-Ereignisse. Keine zusätzlichen
  Ereignisse, Leser, Dateien oder Puffer. Auswahl nach Job, TAR und Transferphase;
  Werte eines vorherigen Schreibpasses werden nicht als aktuelle Rücklesung gezeigt.

## Bedeutung und Grenzen

Worker-CPU ist Prozess-CPU-Zeit pro verstrichener Zeit: 100 % entspricht einem Kern,
mehrere Threads können zusammen mehr als 100 % erreichen. Host-CPU bezieht sich auf
alle Kerne; I/O-Wartezeit steht separat daneben. Es sind Auslastungswerte und keine
SHA-256-Benchmarks. Die erste Differenzmessung bleibt unbekannt. Fehlende Linux-
Zähler werden nicht als Nullwerte ausgegeben; Prozess-CPU bleibt auf macOS verfügbar.

Der Lesepuffer liegt im Host zwischen Gerät und TAR-/Hashprüfung; er ist nicht der
interne Laufwerkspuffer und nicht der größere mbuffer-Schreibpuffer. Eine geringe
Füllung beweist allein keinen Defekt und keine bestimmte mechanische Bewegung.
Fehlender Schreibfüllstand wird als nicht verfügbar angezeigt. Messwerte mit mehr
als 20 Sekunden Alter bzw. ohne frischen Worker-Heartbeat sind als veraltet markiert.

Die Telemetrie ändert weder Rate noch Puffergröße, Verifikation, Gerätepositionierung
oder Jobpläne. Eine automatische Regelung der Bandgeschwindigkeit ist nicht Teil
dieser Anzeige. Im aktuellen Reader gibt es keine sicher im laufenden Prozess
umschaltbare Leseratenregelung.

## Prüfung

317 lokale Softwaretests, davon ein Skip, erfolgreich; zusätzlich JavaScript-
Syntax- und Renderprüfungen. Neue Tests prüfen CPU-Normalisierung, unbekannte bzw.
zurückgesetzte Zähler, fehlende Linux-Dateien, stale Heartbeats, einen gemeinsamen
Commit und die Zuordnung von Pufferwerten zu TAR/Phase. Browserprüfung mit rein
synthetischen CPU-/Pufferwerten. Während laufender Bandarbeit kein Deployment und keine zusätzlichen Servertests.
Im anschließend bestätigten Medienwechsel-Leerlauf bestanden alle 317 Debian-Tests.
Der tatsächliche Mehrbandplan wurde mit privaten SQLite-Kopien und einem Software-
adapter geprüft: nur das zweite Kind ausgewählt, Planhash und Verifikationsmodus
`media` erhalten, elf VERIFIED-Archive des ersten Mediums unverändert.
