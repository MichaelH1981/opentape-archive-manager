# Produktionsfreigabe: Stand 20.10.2026

**Status: FREIGEGEBEN für reguläre Dateiarchivierung auf der abgenommenen IBM-ULT3580-HH4/LTO-4-Konfiguration mit qualifiziertem lokalem Staging.** OTAM **0.8.3** ist installiert; physische Archivierung, explizite Initialisierung unbekannter Medien und bestätigter Mehrbandbetrieb sind aktiviert. Web, Worker und optionaler Katalogdienst sind betriebsbereit. Stand 21.10.2026; abschließende Belege und Grenzen unten. Die nachfolgenden chronologischen Abschnitte enthalten auch historische Zwischenstände und unveränderte Fehlversuche.

Der Produktivkatalog enthält **keine Testmedien, Archive oder Dateieinträge**. Drei Testmedien, elf Testarchive (eins absichtlich unvollständig), 15 Dateieinträge und elf zugehörige Jobs wurden nach unabhängigen SQLite-Backups gezielt entfernt. Benutzer, Quelle, HDD-Qualifikation, Konfiguration, Berichte und dauerhafte Sicherheitssperren bleiben erhalten. Die frühere Abbruchtestkassette wurde anschließend über den separat abgenommenen expliziten Reset als neues produktives Medium registriert; es gibt jetzt zwei READY-Produktivmedien, weiterhin keine Testarchive oder Dateieinträge. Katalogbereinigung allein löscht keine Banddaten und entsperrt kein Medium.

| Abnahme | Befund | Status |
| --- | --- | --- |
| Automatisierte Softwaretests | Aktueller Stand 0.8.3: 266/266 Tests auf Debian bestanden, mit isoliertem lokalem Test-TMPDIR. Lokal 266 Tests mit einem Skip. Keine Tests verändern physische Banddaten oder lösen Shutdown aus | Bestanden für den Kandidaten |
| Reale Laufwerks-/Medienerkennung | IBM ULT3580-HH4 und eindeutig identifiziertes eingelegtes Testmedium; keine aktive TapeAlert-Warnung beim letzten Scan | Bestanden, Momentaufnahme |
| Reales PAX-TAR-/Filemark-/Append-Layout | Fünf Banddateien; alle vor und nach Append zurückgelesen und gehasht | Bestanden im kleinen Testlayout |
| Unabhängige Wiederherstellung ohne OTAM-Installation | Zwei bereits vom Testband zurückgelesene Daten-/Receipt-Paare mit `tools/recover_tar.py` unter isoliertem Python 3 wiederhergestellt: je zwei Dateien, inklusive Archiv- und Ziel-Hashprüfung; temporäre Ziele entfernt | Bestanden für diese Testarchive |
| 256-GiB-Medientest | Vollständiger Schreib-/Rücklesezyklus mit SHA-256; kein echtes Bandende erreicht | Teilabnahme |
| Volles Band bis EOM und vollständig zurücklesen | Der ausdrücklich freigegebene OTAM-Wartungsauftrag erreichte das echte Bandende nach 781,41 GiB rekonstruierbaren Testdaten (`eom=true`). Vollständige Rücklesung und SHA-256-Vergleich bestanden (`0ee3c3af5b6b68327c71464bca6944f520aa5373f793395b4faf7c8b045c4b68`). Kein aktives TapeAlert-Flag; die Laufwerkszähler meldeten drei korrigierte Schreibereignisse und keine unkorrigierten Schreib-/Lesefehler. Kompression war deaktiviert. Der Kapazitätswert gilt bis zum ersten gemeldeten ENOSPC/Frühwarnbereich, nicht als erzwungenes physisches EOT | Bestanden für dieses Testmedium |
| Kontrollierter Abbruch, Neustart und Medienwechsel an echter Hardware | Zwei kleine echte Medienwechsel-Kindaufträge mit Readback/Restore bestanden; tatsächlicher Prozessverlust nach 512 KiB, frische CLI-Rekonsolidierung und frischer Append vor jeder Bewegung verweigert; Live-Pending erhalten | Bestanden; kein Stromausfalltest |
| Reguläre OTAM-Pipeline auf `/dev/nst*` | Kleine Zyklen, Append und verzögerte Verifikation bestanden. Großer Zyklus mit 2 × 70 GiB am 20.10.2026 um 10:00:54 MESZ vollständig VERIFIED. Optimierter gezielter Restore physisch bestanden. Gemeinsamer HTTP-/CLI-/Worker-Zyklus am 20.10.2026 um 13:15:30 MESZ mit zwei neuen TARs, physischer SHA-256-Verifikation und Restore bestanden | Kernzyklus, Web-/CLI, Initialisierung, kleiner Medienwechsel, echter Abbruch-/Neustartnachweis und Betriebsaktivierung bestanden |
| Wiederherstellung eines regulär durch OTAM erzeugten physischen Archivs nach Verlust von Installation und Katalog | Am 20.10.2026 zwei regulär durch ArchiveService geschriebene Archive physisch exportiert und unter isoliertem Python ohne OTAM-Importe mit `tools/recover_tar.py` vollständig wiederhergestellt (2 + 1 Dateien, Archiv- und Ziel-Hashes geprüft). Zusätzlich Katalogrekonstruktion aus leerer DB und regulärer Restore bestanden. Anschließend Header und erstes Paar ausschließlich mit sg3-utils, mt-st und GNU dd gelesen und mit System-Python unabhängig wiederhergestellt; Archivhash identisch, zwei Zieldateien geprüft | Für diese regulären Testarchive bestanden |
| Eigenständiger Katalog auf Proxmox | Debian-LXC mit eigenem `otam`-Dienstkonto und Catalog-Node-Webdienst installiert. Lokaler `/healthz`, Anmeldung, geschützte Dateisuche und gesperrte Archivierungsroute geprüft. Der SSH-Tunnel blieb aktiv; der signierte Katalog-Snapshot (Sequenz 1, 98.304 Byte) wurde nach dem Bandauftrag übernommen. Bei gestopptem Bandserver-Webdienst antworteten die unabhängige Medienansicht und Dateisuche weiterhin; anschließend liefen Webdienst und Worker wieder. Nach dem Neustart des Bandservers wurde auch der Tunnel aktiv; ein expliziter Synchronisierungsauftrag `f5ee9520-0a29-4c1a-9678-e1a853c21fdf` endete `SUCCEEDED/UNCHANGED` für Sequenz 27 | Bestanden für vorhandenen Katalogstand |
| Automatische Katalogsynchronisierung bei belegtem I/O-Lock | Während des HDD-Zonentests wurden 33 automatisch geplante Synchronisierungen in wenigen Minuten als Fehler angezeigt, weil der Scheduler die I/O-Sperre nicht beachtete. Version 0.5.4 stellt fällige automatische Aufträge bis zur Freigabe der Sperre zurück; ein Wettlauf nach dem Einplanen wird als `DEFERRED` ohne Fehlertoast abgeschlossen. Linux-Regressionstest bestanden und Version 0.5.4 auf dem Bandserver installiert. Keine der fehlgeschlagenen Veröffentlichungen änderte den gültigen Peer-Katalog. Direkt nach Ende des Zonentests um 21:03:50 MESZ lief der nächste Auftrag erfolgreich; `sync_log` bestätigt `send/SUCCEEDED`, Sequenz 27 | Fehler behoben; erfolgreicher Nachlauf bestätigt |
| Admin-Shutdown aus der Weboberfläche | Version 0.5.5 bietet eine optional aktivierte, bestätigungspflichtige Schaltfläche für Admin-Konten. Die API prüft Rolle/CSRF/Node-Namen und sperrt neue Jobs; ein separater root-systemd-Helfer prüft I/O und Jobstatus erneut. 128 Softwaretests bestanden; systemd-Units statisch validiert. Echter Shutdown bewusst nicht im laufenden HDD-Test ausgelöst | Softwareabnahme bestanden; realer Shutdown später zu prüfen |
| NAS-Katalogsicherung | Noch kein gemounteter Backup-Pfad mit Zielmarker konfiguriert | Offen für verteilten Betrieb |
| Staging-HDD | Die interne SATA-HDD Seagate S1E02N8E wurde mit ext4 formatiert. Der offizielle 30-Minuten-O_DIRECT-Test bestand mit 200,88 MB/s im Mittel, 140,94 MB/s im schwächsten Fenster und 1,82 % mittlerer CPU-Beschäftigung. Fünf zusätzliche ausschließlich lesende O_DIRECT-Zonenmessungen bis 1,60 TB bestanden das 120-MB/s-FIFO-Puffermodell; Einzelwerte und Last siehe unten. SMART nach den Tests: PASSED, 0 reallozierte/schwebende/unkorrigierbare Sektoren, 0 UDMA-CRC-Fehler; die historischen Werte Runtime_Bad_Block=40 und Command_Timeout=1/1/5 blieben unverändert. Keine passenden Kernel-I/O-Fehler im Testzeitraum. Der Benutzer hat den langen SMART-Test ausdrücklich abgewählt. UUID-basierter, optionaler ext4-Mount und zusätzliche OTAM-Staging-Ressource sind eingerichtet. Nach kontrolliertem Neustart am 19.10.2026 um 21:12 MESZ wurde `/dev/sdb1` wieder automatisch mit `nosuid,nodev,noexec,noatime` eingehängt; die gespeicherte Ressourcen-Geräte-ID stimmt, Webdienst und Worker wurden aktiv | Staging-Leistung, Registrierung und Neustartprüfung bestanden |
| Aktive Staging-Anzeige und SSD-Abmeldung | Version 0.5.7 summiert registrierte lokale Staging-Dateisysteme genau einmal und zeigt Gesamt-, belegte und verfügbare Kapazität. Auf dem Bandserver ist allein `/srv/otam/staging-hdd` aktiv: 1.967.845.998.592 Byte Gesamtgröße, 1.867.807.203.328 Byte für den Dienst verfügbar zum Zeitpunkt der Prüfung. Die beiden SSD-Einträge `/var/lib/otam/staging` und `/srv/otam/staging/zusatz` wurden mit der Ressourcen-Sicherheitsprüfung abgemeldet; Dateien wurden nicht gelöscht. Der primäre Staging-Pfad und die systemd-Schreibfreigaben verweisen nur noch auf die HDD. Historische SSD-Speedtests bleiben als Testdaten erhalten, werden jedoch nicht mehr als aktive Staging-Messungen angezeigt. Webdienst, Worker und `/healthz` waren nach Installation aktiv | Bestanden für die aktuelle Konfiguration |
| Verwalteter Staging-Speedtest und Transferempfehlung | Web-Workflow mit eigener 12-GiB-Testdatei, O_DIRECT-Lesefenstern und CPU-/I/O-Wait-Messung. Version 0.5.3 bewertet kurzzeitige Einbrüche über ein kumulatives FIFO-Puffermodell. HDD-Qualifikation bestanden. Reale Anwendung von 120 MB/s und 2.368 MiB im getrennten physischen Integrationskandidaten nachgewiesen; großer Test enthält Pufferfüllstand-Samples. Version 0.6.0 prüft und verwendet gespeicherte Werte vor jedem physischen Job | Nachgewiesen und produktiv aktiviert |

Der erste **60-Sekunden-Funktionstest** auf dem bisherigen SSD-Staging `/var/lib/otam/staging` erzeugte und entfernte seine eigene 12-GiB-Datei vollständig. Gemessen wurden 457,75 MB/s im Durchschnitt, aber nur 55,09 MB/s im schwächsten Fenster; gegen Ende lagen mehrere volle Fenster um 69–71 MB/s. Die mittlere systemweite CPU-Beschäftigung lag bei 3,4 %, die höchste I/O-Wartezeit bei 61,7 %. OTAM meldete folgerichtig `qualified=false` und schlug unter Lastwarnung lediglich 38 MB/s Schreibrate mit 512 MiB Puffer als unverbindliche Werte vor. Diese SSD ist damit nicht als dauerhafte 120-MB/s-Quelle nachgewiesen. Der kurze Lauf ersetzt ausdrücklich nicht die spätere 30-Minuten-Prüfung der eingebauten HDD.

Eine Freigabe erfordert einen bestandenen echten OTAM-Zyklus **Planung → vollständiges lokales Staging → Band-Write → vollständige physische Rücklesung → SHA-256-Verifikation → gezielter Restore**, eine konservative und nach Neustart sichere Positionierung, einen bestandenen langen Staging-Test am endgültigen Einbauort sowie dokumentierte Fehlerfälle. Bandqualifikation und Testlayout dürfen nur auf einem ausdrücklich für den jeweiligen destruktiven Umfang freigegebenen Medium laufen. Keine der noch offenen Prüfungen darf durch Simulatorergebnisse als bestanden gelten.

Der erste SATA-Test verwendete noch die 0.5.2-Einzelfensterregel; sein historischer Bericht bleibt unverändert. Die Nachrechnung mit dem 0.5.3-Modell ist eine Diagnose, keine rückwirkende Änderung des Jobstatus. Der neue vollständige Testlauf hat die offizielle Qualifikation für den äußeren Plattenbereich erbracht. Die nachfolgenden **direkten, ausschließlich lesenden** Zonenmessungen qualifizieren auch die geplante Belegung bis 1,6 TB. Die Mittelwerte der System-I/O-Wartezeit lagen bei 48,9–49,5 % während dieser bewusst I/O-gebundenen Lesevorgänge. Ein Restdefizit von 10,25 MB am Ende der innersten Zone lag deutlich unter den erlaubten fünf Sekunden Zielrate (600 MB); die anderen Zonen holten jeden Rückstand vollständig auf.

| HDD-Zone | Messdauer | Mittelwert | Schwächstes Fenster | Ø System-CPU | Max. Pufferdefizit | FIFO-Modell |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0,25 TB | 2 min | 197,90 MB/s | 158,26 MB/s | 4,05 % | 0 MB | Bestanden |
| 0,75 TB | 2 min | 181,37 MB/s | 143,44 MB/s | 3,77 % | 0 MB | Bestanden |
| 1,25 TB | 2 min | 156,50 MB/s | 117,24 MB/s | 3,99 % | 2,76 MB | Bestanden |
| 1,55 TB | 10 min | 135,77 MB/s | 91,70 MB/s | 10,13 % | 28,47 MB | Bestanden |
| 1,60 TB | 10 min | 131,63 MB/s | 95,67 MB/s | 10,03 % | 24,53 MB | Bestanden |

Der Zonenbericht liegt auf dem Bandserver unter `/var/lib/otam/reports/hdd-zones-20261019.json`. Für 120 MB/s Zielrate empfiehlt das Modell im inneren Bereich 2.483.027.968 Byte Puffer (rund 2.368 MiB); die 30-Minuten-Prüfung des äußeren Bereichs empfahl 2.304 MiB. Die SSD-Schwäche und die früheren SMART-Historienwerte der HDD bleiben dokumentiert. Die HDD ist nur ein temporärer Staging-Puffer und ersetzt keine Sicherung. Der reguläre physische OTAM-Zyklus und dessen Sicherheitssperren bleiben vor einer Produktionsfreigabe offen.

## Backend-Abnahme am 20.10.2026

Der separat bereitgestellte Kandidat unter
`/var/lib/otam/acceptance-code/physical-20261020` bestand auf Debian eine vollständige
Suite mit 141 Tests und anschließend zwei zusätzliche Fehlerpfadtests. Ein erster
Testlauf kollidierte mit der I/O-Sperre der laufenden automatischen Synchronisation;
der erfolgreiche Softwarelauf verwendete daher einen eigenen lokalen Test-TMPDIR,
ohne die gemeinsame Sperre echter Archivierungsaktionen zu verändern. Die lokale
Weiterentwicklung mit nur innerhalb einer Laufwerkssperre gültigem Metadaten-/EOD-
Cache bestand 144 Tests (43 Linux-spezifische Tests unter macOS ausgelassen). Diese
Optimierung ist noch nicht Teil des laufenden Hardwareprozesses.

Der erste reguläre physische Funktionstest startete um 01:56 MESZ als
`otam-physical-pipeline-smoke.service`. Er verwendet den echten ArchiveService und
LinuxTape, ausschließlich generierte Testdateien (zweimal 32 MiB plus README), das
qualifizierte HDD-Staging und die ausdrücklich freigegebene Kassette. Die
Initialisierung inklusive vollständiger Header-Rücklesung ist bestätigt. Der
unveränderte Plan enthält zwei TARs und 67.108.909 Nutzbytes; beide TARs wurden
vollständig lokal vorbereitet. Archiv-Readback, Katalogrekonstruktion und Restore
laufen als weitere Schritte desselben Testprozesses. Der Bericht wird unter
`/var/lib/otam/reports/physical-pipeline-smoke-20261020-0158/report.json` gespeichert.
Der historische Bericht endete um 02:11 MESZ mit FAILED beim Restore. Zuvor waren
beide Archive vollständig geschrieben und physisch SHA-256-verifiziert worden;
auch die Rekonstruktion in einer leeren SQLite-Datenbank ergab zwei vollständige
Archive ohne Tail. Der Kernel protokollierte exakt
`Failed to read 524288 byte block with 10240 byte transfer.` Der Fehler ENOMEM
bezeichnet hier gemäß der installierten Linux-st-Dokumentation einen zu kleinen
Lesepuffer für den nächsten Bandblock. Es lag kein RAM-Mangel vor. Der TAR-Restore
benutzte seinen 10-KiB-Standardpuffer direkt am variablen 512-KiB-Bandrecord.

Die Geräteabstraktion puffert nun ganze Records und merkt sich das erste physische
EOF dauerhaft bis zum Schließen dieser Banddatei. Das ist wesentlich: eine normale
Pufferung ohne EOF-Sperre könnte nach einem kurzen letzten Read bereits die nächste
Banddatei einlesen. Regressionstests prüfen kleine Leser, vollständige Records,
wiederholtes EOF ohne weiteren Geräte-Read und unverändert propagierte Lesefehler.
Die lokale Suite besteht damit aus 146 Tests (43 Linux-spezifische Tests ausgelassen).
Der separate Kandidat unter
`/var/lib/otam/acceptance-code/physical-recordfix-20261020` bestand anschließend
alle 146 Tests auch auf Debian. Der ausschließlich lesende Wiederholungszyklus
läuft als `otam-physical-restore-recheck.service`; sein Bericht liegt unter
`/var/lib/otam/reports/physical-restore-recheck-20261020-0220/report.json`.
Er rekonstruiert erneut eine leere Datenbank, stellt die vorhandenen Testdateien
wieder her und prüft die unabhängige Wiederherstellung physisch exportierter TARs
mit isoliertem Python ohne OTAM-Importe. Das Medium wird dafür nicht neu
initialisiert oder ergänzt. Der Nachtest endete um 02:21 MESZ erfolgreich:
Rekonstruktion, Restore aller drei Dateien und unabhängige Wiederherstellung beider
TARs bestanden. Bericht-SHA-256:
`bbcb57f71d0c6a0117523f51e9224de9eb70e9eab3aea110507b573fc3ae4aa3`.
Die Archiv-Hashes lauten
`f8d0ff98d5a8c82d9b4c2f23ede8d5912efed3ac62974471b8f28dd51a7b0101`
und `8b9530360e1acf2686231d17eb707147bb81367a9527d17b7f07b5932fc54954`.
systemd startete anschließend den regulären Worker wieder.
Der fehlgeschlagene Originalbericht bleibt unverändert und ist im lokalen Rohdaten-
Dossier mit SHA-256 `4385021c1e116d66349514c61274985404a6d6941cff11e34d9635a623323379`
gesichert. Der reguläre Worker wurde nach Testende automatisch wieder aktiv.

Dies ist keine Produktionsfreigabe und kein Leistungstest großer TARs. Die
installierten Dienste bleiben auf Version 0.5.7; die physische reguläre Webroute ist
weiter gesperrt. Die Backend-Entscheidungen und verbleibenden Sperrpunkte stehen in
[physical-backend.md](architecture/physical-backend.md).

Seit 02:21 MESZ lief getrennt `otam-physical-pipeline-append.service` mit demselben
geprüften Kandidaten: zwei weitere 32-MiB-Dateien, Anhängen an dieselbe Medien-ID,
Verifikation erst nach dem gesamten Schreibsegment und anschließend Rekonstruktion
und Restore. Der Bericht liegt unter
`/var/lib/otam/reports/physical-pipeline-append-20261020-0225/report.json`.
Er endete um 02:24 MESZ mit VERIFIED: Zwei neue Archive angehängt, danach alle
vier Archive mit ihren Receipts vollständig physisch geprüft, aus leerem Katalog
rekonstruiert und die drei neuen Dateien wiederhergestellt. Es gab keinen Tail;
das bestehende Präfix blieb durch seine vollständigen Hashprüfungen bestätigt.
Bericht-SHA-256: `4204d83fff9857dac9d1f57a8dbfa26ca909981f660478970432c1cff375fd76`.

Der zusätzliche GNU/Linux-Gerätetest `otam-physical-gnu-recovery-r2.service`
las Header und Banddateien 1/2 mit `dd bs=1M conv=excl`, bestätigte jeweils die
Position aus BOT und stellte mit System-Python und dem eigenständigen Helfer zwei
Dateien wieder her. Kein OTAM-Modul war an diesem Lesepfad beteiligt. Archivhash
`f8d0ff98d5a8c82d9b4c2f23ede8d5912efed3ac62974471b8f28dd51a7b0101`
ist identisch zum regulären Archiv. Bericht-SHA-256:
`36fe463833fbc8cac1f61b38eb21ec50dbc3604967251bb7e23028705ba9286c`.
Ein vorheriger Harness-Lauf verwendete irrtümlich `oflag=excl`; GNU dd lehnte das
vor dem Datenlesen ab. Der korrigierte Schalter ist `conv=excl`; auch dieser
fehlgeschlagene historische Bericht bleibt separat erhalten.

## Großer Archivzyklus mit Transfersteuerung

Der nächste Kandidat unter
`/var/lib/otam/acceptance-code/physical-transfer-20261020` bestand 149/149
Debian-Tests. Er setzt das gewählte unterstützte Host-Datenstromlimit mit mbuffer
`-R`, füllt den Puffer vor dem Schreiben zu 90 Prozent und erhält dessen rohe
Statuslogs dauerhaft unter `state/transfer-logs/`. Einmal pro Sekunde werden
erkannte Füllstände in den Jobfortschritt übernommen; fehlende Samples bleiben
unbekannt. Vor Öffnen zum Schreiben muss genügend verfügbarer RAM einschließlich
Reserve vorhanden sein. Die gespeicherten Web-Transferwerte bleiben bis zur
regulären Webintegration weiterhin ausdrücklich vorgemerkt, nicht global aktiv.
Ein isolierter mbuffer-Funktionstest ohne Band bestätigte Vorfüllung, Rate und
Logformat; 16 MiB bei 1 MiB/s benötigten 16,12 Sekunden. Der Test erzeugte und
entfernte ausschließlich eigene temporäre Dateien.

Seit 02:56 MESZ läuft `otam-physical-pipeline-large.service`: zwei synthetische
70-GiB-Nutzdateien (zusammen rund 150,3 GB) plus README, vollständig lokales
HDD-Staging, zwei große TARs, Append an dieselbe ausdrücklich freigegebene
Kassette, verzögerte vollständige Rücklesung, leere Rekonstruktionsdatenbank und
vollständiger Restore. Testwerte: 120.000.000 Byte/s Hostlimit, 2.368 MiB Puffer,
90 Prozent Vorfüllung. Der Bericht liegt unter
`/var/lib/otam/reports/physical-pipeline-large-20261020-0300/report.json`.
CPU-, Speicher- und I/O-Abrechnung sind für die Unit aktiviert. Die generierten
Quellfixtures liegen separat auf der System-SSD; **kein SSD-Staging wurde
registriert oder verwendet**. Sie bleiben nach dem Test erhalten.

Zwischenstand am 20.10.2026 um 07:18 MESZ: Der reguläre Archivjob meldete
um 07:14:30 nach vollständiger physischer Rücklesung beider großer TARs
`VERIFIED` (150.323.855.405 Nutzbytes, drei Dateien). Anschließend begann
`REBUILD_START` für die leere Rekonstruktionsdatenbank. Der übergeordnete
Abnahmeauftrag läuft weiterhin; Rekonstruktion, vollständiger Restore und
abschließende Transfer-/Ressourcenauswertung sind noch nicht bestätigt.

Um 08:05:12 MESZ war die Rekonstruktion aller sechs Archive erfolgreich beendet,
ohne unvollständigen Tail. Um 08:58 MESZ läuft die eigentliche Extraktion;
README und eine noch unvollständige erste Nutzdatei sind im eigenen Restore-Ziel
sichtbar. Das ist weiterhin kein abgeschlossener Restore-Nachweis.

Parallel wurde lokal ein sequenzieller Restore-Kandidat implementiert: Daten vor
Receipt lesen, ausgewählte Dateien während desselben Prüfpasses privat
extrahieren, erst nach erfolgreicher vollständiger Prüfung exklusiv
veröffentlichen. Relative Vorwärtspositionierung bleibt statusgeprüft.
154 lokale Tests sind erfolgreich (43 Linux-spezifische Tests übersprungen).
Zusätzliche Tests sichern die einmalige geordnete Datenlesung, beschädigte
TAR-Endblöcke/Receipts, Katalogabweichungen und bestätigte Filemark-Positionierung
ab. Der Kandidat ist **nicht installiert**; Linux-Nachtest und physischer
Read-only-Restore folgen erst nach Abschluss des unberührten laufenden Tests.

### Abschluss des großen Zyklus

Am 20.10.2026 um **10:00:54 MESZ** endete der gesamte Auftrag erfolgreich mit
`VERIFIED`: drei wiederhergestellte Dateien, beide 70-GiB-Nutzdateien und README,
mit identischen Quell-/Ziel-SHA-256. Die leere Katalogrekonstruktion fand sechs
Archive, einschließlich der vier alten Paare, ohne unvollständigen Tail.
Die beiden großen TARs liegen an Position 9 und 11, jeweils 75.161.937.920 Bytes.
Ihre SHA-256-Werte sind:

* `85c1417ccafcf51b0dfd5a3569daad75ba7b24cd234ad48fd9a4c237a5a19a47`
* `2aa40eb56c15bb82cce5d241e6b057f704e4332f521faa91fddfced4e9f822ba`

Je Archiv wurden 620 Schreibfortschritt-Samples gespeichert. Die abschließend
gemeldeten mittleren Schreibraten betragen 115,76 und 116,05 MB/s einschließlich
Anlauf/Vorfüllung. Erkannte Füllstände: 1–100 Prozent; kein Nullstand in den
Samples. Der niedrige Endwert gehört zum Entleeren am Streamende und belegt
keinen Engpass. Interne mechanische Laufwerkspositionierungen wurden nicht
gemessen; aus den Samples wird keine Bewegungsfreiheit behauptet.

Gesamtlaufzeit etwa 7 h 4 min 34 s, CPU-Zeit 4 h 13 min 52 s; Spitzenwert der
systemd-Speicherabrechnung 7.380.733.952 Bytes einschließlich Dateicache.
Lokale I/O-Abrechnung: 2.400.392.413.184 gelesene und 451.016.380.416 geschriebene
Bytes. Die hohe Lesemenge enthält wiederholte Hash-/Validierungspassagen des
alten Codes und ist keine reine Band-Transfermenge.

Beide Staging-Archive sind erst nach Verifikation als `STAGING_CLEANUP/COMPLETE`
bereinigt. Eigene Quellfixtures und Restore-Ausgabe bleiben erhalten. Worker,
Web und Katalogtunnel sind aktiv; Katalogsync meldet Sequenz 95 `UNCHANGED`.
SMART nach dem Lauf: 2.786 Stunden, keine realloc/pending/offline/CRC-Sektoren,
historische Werte Runtime_Bad_Block 40 und Command_Timeout 1/1/5 unverändert.
Kein langer SMART-Test durchgeführt.

Berichts-SHA-256:
`e98a0c6db89c27cae9c13b0ea815ddf277dd41d9417fd4c82c071a567c4b4b5f`.
Bericht, Transfer-Samples/Logs, systemd-Abrechnung, Journal und SMART-Auszug sind
lokal im ausgeschlossenen Rohdatendossier gesichert. Keine Produktionsfreigabe:
gezielter optimierter Restore und Sicherheits-/Web-/CLI-Abnahmen stehen aus.

Der sequenzielle Kandidat bestand anschließend **154/154 Debian-Tests**.
Eine weitere lokale Erweiterung (156 Tests, 43 Linux-Skips) prüft beim gezielten
Restore nur die ausgewählten Datenarchive und ihre vorausgehende Receipt-Kette;
nicht ausgewählte Nutzdaten werden nicht als verifiziert ausgegeben. Nach dem
letzten gewählten Beleg endet der Scan. So kann die physische Nachprüfung mit
einem kleinen Archiv erfolgen, ohne die großen TARs erneut vollständig zu lesen.

### Gezielte physische Restore-Nachprüfung

Am 20.10.2026 um 10:22 MESZ bestand anschließend der rein lesende Test
`otam-physical-targeted-restore.service` mit dem 156-fach unter Debian geprüften
gezielten Kandidaten. Genau das kleine Daten-TAR an Position 1 wurde einmal
gelesen, zwei Dateien aus einer isolierten Katalogkopie in ein neues Ziel
wiederhergestellt und gegen die ursprünglichen Fixture-SHA-256 geprüft.
Keine anderen Nutzarchive wurden gelesen und kein Bandinhalt geschrieben.
Aufgezeichnete Positionierungskommandos: einmal `eod` zur Bestätigung der
Banddateianzahl und einmal `rewind` zum Header; danach wurden Header, Daten und
Receipt ohne weitere Bewegungsbefehle gelesen. Gesamtdauer rund 25,30 Sekunden.
Das ist ein funktionaler Nachweis des sequenziellen und selektiven Lesepfads,
kein direkter Leistungsvergleich mit einem vollständigen großen Restore.
Bericht: `/var/lib/otam/reports/physical-targeted-restore-20261020-r1/report.json`.
Die regulär installierten Dienste bleiben unverändert auf 0.5.7; insbesondere
Web-/CLI-Archivierungsfreigabe und reale Abbruch-/Neustartsperren sind noch offen.

### Nichtdestruktive Sicherheitsprüfung am Laufwerk

Der Kandidat `da06f91` bestand 157/157 Debian-Tests. Anschließend bestand am
20.10.2026 um 10:51 MESZ `otam-physical-safety-preflight.service` folgende Gates
am tatsächlich erkannten Laufwerk: falsche Laufwerksseriennummer, falsche
MAM-Seriennummer und abweichender Gerätepfad wurden abgewiesen; ein zweiter
Laufwerkszugriff scheiterte an derselben exklusiven Sperre. Ein separater Prozess
erzeugte ausschließlich im neuen privaten Abnahmeverzeichnis einen fsync-
gesicherten Test-Pending-Marker und endete abrupt ohne Bereinigung. Eine neue
Backend-Instanz verweigerte Append daraufhin bereits vor Headerlesen,
EOD-/BOT-Bewegung und Öffnen eines Schreibdeskriptors. Der persistente Marker
bleibt im isolierten Abnahmeverzeichnis zur Nachvollziehbarkeit erhalten.

Es wurden keine Banddaten gelesen, geschrieben oder positioniert; lediglich
der vorhandene variable Blockmodus wurde gesetzt. Diese Prüfung belegt die
realen Identitäts-/Exklusivitätsgates und die Sperre bei erhaltenem Testmarker.
Sie ersetzt **keinen tatsächlichen Abbruch während physischem Bandschreiben**.
Dieser Nachweis bleibt offen und wird erst nach den übrigen Integrationsschritten
mit kleinem synthetischem Append geplant, damit keine unnötige Wiederholung
der großen erfolgreichen Zyklen entsteht. Produktionsfreigabe bleibt gesperrt.
Bericht: `/var/lib/otam/reports/physical-safety-preflight-20261020-r1/report.json`.
Worker, Webdienst und Katalogtunnel sind nach dem Test wieder aktiv.

### Vermeidung wiederholter alter Nutzdatenprüfungen

Ein weiterer, noch nicht installierter Kandidat prüft vor regulärer physischer
Planung/neuem Append nur den exakten Header, EOD/Dateianzahl, Tail und die komplette
Prüfbeleg-Kette gegen den bereits VERIFIED geführten Katalog. Unbekannte oder
unbestätigte Sequenzen sperren den Job. Neue Datenarchive werden weiterhin
vollständig physisch gehasht; bei verzögerter Verifikation werden nur die Archive
des aktuellen Jobs und ihre vorausgehende Receipt-Kette gelesen. Vollprüfung,
Rekonstruktion und explizite Wiederaufnahme behalten den vollständigen Scan.
Es wird kein neuer Integritätsnachweis für ungelesene alte Nutzdaten behauptet.

160 lokale Tests bestanden (43 Linux-Skips). Die physische Adapter-/Service-
Simulation prüft nun je einen zweiten Append für beide Verifikationsmodi und
weist nach, dass keine alten Datenarchive, aber jedes neue Daten-TAR genau einmal
zur Verifikation gelesen wird. Zusätzliche Negativtests sperren geänderte
Receipts, unbekannte/unbestätigte Katalogsequenzen und unvollständige Tails;
ein absichtlich beschädigtes altes Payload bleibt bei Receipt-Vorprüfung
unentdeckt, muss aber bei expliziter Vollprüfung korrekt scheitern.
Anschließend bestanden **160/160 Debian-Tests** unter dem getrennten Kandidaten
`/var/lib/otam/acceptance-code/physical-receipts-20261020` (`a74aa8d`), mit
isoliertem lokalem Test-TMPDIR. Gezielt physisch zu prüfen ist diese Änderung
zusammen mit dem noch zu integrierenden regulären Web-/CLI-Archivpfad; dafür
wurde kein weiterer Bandlauf gestartet. Installierte Dienste bleiben unverändert.

### Regulärer Web-/CLI-Integrationskandidat

Ein neuer gemeinsamer Pfad in `web/physical_archive.py` bindet bestehende
physische OTAM-Medien an Medien-UUID, MAM- und Laufwerksseriennummer. Die
Geräteadresse wird aus aktueller Erkennung aufgelöst und vom Backend unmittelbar
vor Gerätezugriff erneut geprüft. Admin-Auftrag `register-physical` liest
vorhandene Medien; er initialisiert niemals. Rollenprüfung und DE/EN-Oberfläche
enthalten die lesende Registrierung unter Hardware.

Das neue Konfigurationsgate `physical_archiving` ist standardmäßig **false**.
Es wurde auf dem Bandserver nicht aktiviert. Normaler Worker und CLI-Warteschlange
verwenden dieselbe Validierung. Die gespeicherten Transferwerte werden gegen
Profil und Staging-Dateisystem geprüft und an LinuxTape übergeben; ausgewählte
Werte werden als Jobereignis protokolliert. Ohne passende Werte wird kein Write
gestartet. Staging benötigt nach geprüfter Planung kein eingelegtes Medium.

170 lokale Tests bestanden (43 Linux-Skips), einschließlich des regulären
Workerzyklus Registrierung → Plan → Offline-Staging → verzögerte Verifikation →
Restore gegen die Dateigeräteemulation, mit Prüfung von `-R 120000000` und
`-m 2368M`, physischer Serienbindung bei wechselndem nst-Namen, veralteter/falscher
Erkennung, geändertem Dateisystem, ungültigen Transferwerten, CLI-Idempotenz und
standardmäßig gesperrtem Write-Gate. JavaScript-Syntaxprüfung bestanden.
Anschließend bestanden **170/170 Debian-Tests** unter dem getrennten Kandidaten
`/var/lib/otam/acceptance-code/physical-web-integration-20261020` (`88086de`).
Ein kleiner echter Web-/CLI-Integrationszyklus steht noch aus und soll die
Receipt-Vorprüfung und wirksamen Transferwerte gemeinsam prüfen. Die bereits
bestandenen großen Datenzyklen werden dafür nicht wiederholt.

Scope dieses Kandidaten: ein bereits initialisiertes physisches Medium. Physische
Initialisierung und Mehrbandplanung bleiben gesperrt und benötigen eigene sichere
Workflows. Die bisherige Simulator-Mehrbandfunktion ist unverändert. Die
Produktionsabnahme ist deshalb weiterhin offen; die Installation bleibt 0.5.7.

### Kleiner gemeinsamer HTTP-/CLI-Hardwarezyklus

Der Abnahmeharness `tools/tape_web_cli_acceptance.py` und seine transaktionalen
Katalogimport-Tests bestanden 173/173 Debian-Tests. Unter separatem Codepfad
`/var/lib/otam/acceptance-code/physical-http-cli-20261020` (`545f2a5`) läuft seit
20.10.2026 12:24:27 MESZ `otam-physical-http-cli.service`. Bericht:
`/var/lib/otam/reports/physical-http-cli-20261020-r1/report.json`.

Der Test verwendet zwei eigene 1-MiB-Dateien plus README, isolierte Konfiguration,
Anmeldung, Steuerung und Katalogkopie sowie das vorhandene HDD-Staging. Er prüft
die reale HTTP-Anmeldung/CSRF, lesende Medienregistrierung, Speicherung der
Transferwerte, Planung, CLI-Staging über die dauerhafte Warteschlange, normales
Worker-Backup mit verzögerter Verifikation und HTTP-Restore. Die Geräteklasse
wird ausschließlich zur Beobachtung von Datenlesepositionen und Bewegungsbefehlen
abgeleitet; alle Basissicherheitsprüfungen bleiben unverändert. Initialisierung
ist im Harness ausdrücklich gesperrt. Alter Payload darf nicht erneut gelesen
werden; das Überspringen alter Daten zu den Prüfbelegen erfordert weiterhin
physische Vorwärtspositionierungen und ist kein vollständiger Payload-Scrub.

Erst nach erfolgreicher vollständiger neuer TAR-/Datei-Verifikation und Restore
dürfen ausschließlich die neuen verifizierten Archivmetadaten mit Herkunftslog
atomar in den unveränderten Livekatalog übernommen werden. Fehlende Verifikation,
geänderter Katalogpräfix oder Importfehler sperren dies; Softwaretests sichern
auch vollständiges Rollback bei Fehler nach dem ersten Datensatz.

Der Hauptworker ist für den Lauf kontrolliert angehalten und startet durch
OnSuccess/OnFailure wieder; Web und Tunnel bleiben aktiv. Die Livekonfiguration
und ihre Produktionssperre bleiben unverändert. Den laufenden Kandidaten nicht
verändern oder durch parallele Geräte-/I/O-Tests stören. Ein Ergebnis ist noch
nicht bestätigt; bei Fehler keine blinde Wiederholung oder Neuinitialisierung.

Den laufenden Auftrag und sein Code-Verzeichnis nicht verändern oder durch
weitere intensive I/O-Tests stören. Der reguläre Worker ist bis zum Testende
angehalten und startet anschließend über OnSuccess/OnFailure automatisch.
Keine Produktionsfreigabe vor Auswertung dieses Laufs und der verbleibenden
Sicherheits-/Web-/CLI-Abnahmen.

#### Ergebnis des ersten HTTP-/CLI-Laufs und Korrektur

Der Lauf endete am 20.10.2026 um 12:29:09 MESZ **FAILED**, vor jedem
Schreibzugriff. Die lesende Registrierung bestand; Datenlese- und Schreiblisten
sind leer. Danach verweigerte die HTTP-Transferauswahl korrekt das inzwischen
veraltete Hardwareprofil. Die Registrierung hatte durch physische Positionierung
zu den Receipts länger als die Profilgültigkeit von 120 Sekunden gedauert.
Der synchrone Abnahmeharness verwendet `run_once`, jedoch nicht die periodische
Zwischenjob-Erkennung der normalen Workerschleife.

Der korrigierte Harness führt zwischen abgeschlossenen Aufträgen bei veralteter
Erkennung denselben echten Diagnostikscan wie der normale Worker aus. Er setzt
keinen alten Zeitstempel neu und verlängert keine Sicherheitsfrist. Zwei neue
Regressionstests prüfen die erforderliche echte Erkennung und das Vermeiden
zusätzlicher Geräteabfragen bei noch aktueller Erkennung. Lokal bestehen
175 Tests (ein plattformbedingter Skip). Der ursprüngliche Fehlerbericht und
das Journal bleiben unverändert lokal gesichert. Web, Worker und Tunnel wurden
nach dem Fehlende wieder aktiv; die Installation und Produktionssperre sind
unverändert.

Der korrigierte Kandidat `59422e5` bestand anschließend **175/175 Debian-Tests**
im eigenen zugänglichen Code-Arbeitsverzeichnis und mit isoliertem Test-TMPDIR.
Eine zuvor versehentlich aus dem für `otam` unzugänglichen Home-Verzeichnis
des SSH-Benutzers gestartete Softwaremessung scheiterte an Zugriffsrechten auf
das Arbeitsverzeichnis; auch deren Log bleibt erhalten. Das ist kein bestandener
Testlauf und kein physischer Bandfehler.

Seit **12:54:15 MESZ** läuft der korrigierte kleine Integrationszyklus als
`otam-physical-http-cli-r2.service` mit unveränderlichem Code unter
`/var/lib/otam/acceptance-code/physical-http-cli-inventory-20261020`.
Neuer Bericht: `/var/lib/otam/reports/physical-http-cli-20261020-r2/report.json`.
Die Test-ID ist `0d579a37-aad6-4371-9867-1797da07a5c3`; anfänglich sind weiterhin
13 Banddateien vorhanden. Der Hauptworker bleibt bis zum Ende dieses Laufs
angehalten und wird über OnSuccess/OnFailure wieder gestartet. Keine parallelen
Gerätejobs oder intensiven Servertests starten. Ergebnis und Livekatalogimport
dieses Laufs sind noch offen; die Produktionssperre bleibt aktiv.

#### HTTP-/CLI-Zyklus r2 vollständig bestanden

Der korrigierte Lauf endete am **20.10.2026 um 13:15:30 MESZ VERIFIED**,
nach 1.273,54 Sekunden. Es wurden ausschließlich Banddateien 13–16 angehängt:
zwei Daten-TARs mit je 1.054.720 Byte an Position 13/15 und Receipts an 14/16.
Die Datenpositionen wurden jeweils genau einmal für die Rückleseprüfung und
einmal für Restore gelesen; keine alte Payloadposition wurde an den Host gelesen.
Die physischen Vorwärtspositionierungen zu alten Receipts bleiben im Journal
sichtbar und sind nicht mit vermiedener mechanischer Bewegung gleichzusetzen.

Alle drei Quell-/Zieldateihashes wurden nach Testende unabhängig erneut geprüft.
Der Livekatalog enthält nun acht VERIFIED-Archive; die Archivfolge einschließlich
des bisherigen Präfixes stimmt mit der isolierten Testkopie überein. Die beiden
neuen TAR-SHA-256 lauten
`926529a51a1c46d5ddd9d63f9d17e34e32bf86f23b7f9404d673406c1d5b3ad7`
und `ad85902ad68e910c4927bfa5c3ee646d43007c762c10d202e1af1401e662cc9d`.
Der Bericht hat SHA-256
`00797008418f086c6c5d78d0987c913bc23cf3c0abb5d57041e9a31c6889623e`.

Alle vier tatsächlichen Schreibfortschrittsereignisse bestätigen die gespeicherte
Hostbegrenzung 120.000.000 Byte/s und den Puffer 2.483.027.968 Byte (2.368 MiB).
Bei diesen kleinen TARs liegen keine mbuffer-Füllstand-Samples vor; hierfür ist
der bereits bestandene große Test der Nachweis. Die kleinen Transferraten sind
keine Leistungsmessung. Unit-Abrechnung: 4,95 Sekunden CPU, 116.121.600 Byte
MemoryPeak einschließlich Cache, 2.379.776 Byte lokales Lesen und 14.462.976 Byte
lokales Schreiben. Web, Worker und Tunnel sind wieder aktiv. Der Katalogpeer
bestätigte anschließend die erfolgreiche Übertragung der Sequenz 129.
Rohbericht, unabhängige Nachprüfung, Journal und Transferlogs sind ausschließlich
im ignorierten lokalen Dossier mit SHA256SUMS gesichert.

#### Zusätzliche Neustartsicherung im Kandidaten

Bei der Vorbereitung des echten Abbruchtests fiel eine Statuslücke auf: Der
Workerstart unterbrach zwar die dauerhaften Steueraufträge, ein Katalogjob konnte
aber bis zum expliziten Recover weiter RUNNING anzeigen. Der neue Kandidat
korrigiert dies nach exklusiver Worker- und I/O-Sperre bereits lokal beim Start:
RUNNING/PLANNING-Jobs werden INTERRUPTED, WRITING-Archive INCOMPLETE, betroffene
Medien SUSPECT und aktive Restore-/Staging-Einträge INTERRUPTED. Die zugehörigen
Katalogänderungen und Ereignisse bilden eine SQLite-Transaktion. Bereits
verifizierte Archive, Staging-Dateien, deren Hashes, Fortschrittswerte und
Pending-Marker bleiben erhalten. Es gibt keine Bandabfrage, Positionierung oder
automatische Wiederaufnahme. Explizites Recover verwendet denselben Statuspfad
weiterhin erst nach Medienidentitätsprüfung.

Vier neue Softwaretests prüfen tatsächliches Ende eines separaten Prozesses mit
anschließendem CLI-Workerneustart ohne eingelegtes Gerät, erhaltene Daten und
Marker, fehlende automatische Wiederholung, idempotente Statuskorrektur,
transaktionales Rollback bei Fehler sowie Medien-/I/O-Sperren. Diese Tests sind
**kein Nachweis eines tatsächlich unterbrochenen physischen Schreibvorgangs**.
Insgesamt bestehen 179 lokale Tests (ein Skip) und **179/179 Debian-Tests** unter
`/var/lib/otam/acceptance-code/physical-restart-catalog-20261020`. Die anschließend
auf `sqlite3.IntegrityError` präzisierte Rollback-Assertion wurde mit allen vier
Neustarttests zusätzlich lokal und unter Debian in einem getrennten
Testverzeichnis geprüft. Der laufende Dienstcode wurde nicht verändert.
Dieser Hardwaretest bleibt offen und soll erst nach den übrigen positiven
Medienworkflows stattfinden, da er einen absichtlich gesperrten Tail erzeugt.
Keine Installation oder Produktionsfreigabe durch diesen Softwarestand.

### Gegateter physischer Mehrbandkandidat und Offlineplanung

Der nächste Kandidat ergänzt `physical_multivolume=false` als unabhängige
Freigabesperre. Nur zusätzlich zu `physical_archiving=true` kann der neue
Workerpfad geordnete physische Mediengruppen planen und je bestätigtem Medium
einen Child-Job schreiben/verifizieren. Die Livekonfiguration und installierte
Version wurden nicht geändert. Initialisierung bleibt ausdrücklich gesperrt.

Web-/CLI-Planung verwendet nun konservative registrierte Katalogprojektionen,
ohne Laufwerkserkennung, Geräteöffnung oder Bandbewegung. Katalogidentität,
READY/IN_USE, lückenlose VERIFIED-Archivfolge, Größen/Hashes/Kapazität sowie
bekannte lokale Pending-Marker werden kontrolliert. Vor jedem tatsächlichen
Schreiben bleiben frische Drive/MAM-Prüfung, echte EOD-/Receipt-/Tail-Prüfung
und die Abweisung veralteter Pläne verbindlich. Die physische Kern-API mit
übergebenem Gerät behält ihre Vorprüfung; der Worker verwendet den ausdrücklich
separaten Katalogplanpfad. Die Oberfläche unterscheidet planbare und eingelegte
Medien und erklärt, dass die Planung keine physische Verifikation ist.

Der Mehrbandschritt wendet die gespeicherten Puffer-/Ratenwerte auf das nächste
eingelegte Medium an und protokolliert sie am Child. Erst nach dessen vollständiger
Rückleseprüfung wird WAITING_MEDIA beziehungsweise abschließend VERIFIED
gespeichert. Falsche, fehlende oder nicht nächste Medien werden ohne Writer
abgewiesen. Für einen verlorenen Parent-Abschluss bei bereits VERIFIED Kindern
genügt die erneute Prüfung von Header/EOD/Receiptkette auf dem letzten Medium;
das behauptet keinen neuen Payload-Scrub und wiederholt keine großen Datenreads.

**185 lokale Tests (ein Skip) und 185/185 Debian-Tests** bestehen unter
`/var/lib/otam/acceptance-code/physical-multivolume-20261020`.
JavaScript-Syntaxprüfungen bestanden. Neue Tests verwenden zwei unabhängige
Dateigeräte hinter dem echten LinuxTape-/ArchiveService-/Workerpfad: Offlineplan
und Staging ohne Gerät, falsches und fehlendes Medium ohne Write, bestätigter
Wechsel, SHA-256-Rücklesung und Restore beider Gruppen, wirksame Transferwerte,
veralteter Plan nach Append sowie Parent-Abschluss ohne zusätzliche Payloadreads.
HTTP prüft außerdem planbare nicht eingelegte Medien und das geschlossene Gate.
Dies ist ausdrücklich **keine physische Zwei-Kassetten-Abnahme**.

Zusätzlich bestand auf dem Bandserver ein rein katalogbasierter Integrationscheck
an einer separaten SQLite-Backup-Kopie des tatsächlichen Livekatalogs mit acht
verifizierten Archiven. Eigene vorhandene synthetische 2-MiB-Quellen ergaben zwei
TARs, erwartete Banddateianzahl 17 und einen unveränderten Live-Archivpräfix.
Geräteerkennung und LinuxTape-Konstruktion waren durch Assertions vollständig
verboten. Bericht:
`/var/lib/otam/reports/physical-offline-plan-20261020-r1/report.json`.
Keine Bandaktion, Quelländerung oder Mutation des Livekatalogs fand dabei statt.
Bericht, Harness und Debian-Testlog bleiben im ignorierten Rohdatendossier.

Offen bleiben explizite Initialisierung mit eigenständiger Freigabe,
physischer Wechsel zwischen zwei konkret autorisierten Testkassetten und
abschließend der echte kleine Schreibabbruch samt Tail-/Neustartsperre. Nur die
bisherige Testkassette ist freigegeben; andere Medien werden nicht verwendet.
Restore bleibt je ausgewählter Medien-/Archivgruppe bestätigt; ein automatischer
medienübergreifender Restore ist nicht als abgeschlossen zu verstehen.
Siehe [Mehrbandarchitektur](architecture/physical-multivolume.md).

Ein zusätzlicher Identitätstest schützt gegen zwei Katalog-UUIDs für dieselbe
physische MAM-Kassette: Sie dürfen nicht als doppelte Kapazität in einen
Mehrbandplan eingehen. HTTP-/Worker-Validierung und Kernplanung verweigern dies
vor dem Speichern eines Plans. Der bisherige vollständige Simulator-Prüfpfad
bei verlorenem Parent-Abschluss bleibt erhalten; nur physische bereits VERIFIED
Kindarchive nutzen die Receipt-Rekonsolidierung ohne erneuten Payload-Scrub.
Der abschließende Kandidat unter
`/var/lib/otam/acceptance-code/physical-multivolume-final-20261020` besteht
**186/186 Debian-Tests**. Lokal bestehen 186 Tests mit einem Skip; die nachfolgende
Simulator-Abschlusskorrektur wurde gezielt mit dem vollständigen Zwei-Medien-Test
und den drei physischen Dateigerätetests nachgeprüft. Keine Installation oder
Bandaktion folgte daraus.

### Initialisierungskandidat bereit für zweite Testkassette

`physical_initialization=false` bleibt das separate Default-Gate. Der neue
Adminworkflow umfasst einen sichtbaren Review unter Hardware, DE/EN-Texte,
Admin-/CSRF-geschützte Vorbereitung und den dauerhaften Workerauftrag
`initialize-physical`. Die CLI kann denselben Auftrag einreihen. Die installierte
Konfiguration und Version 0.5.7 wurden nicht verändert.

Grants sind fünf Minuten gültig, einmalig und transaktional reserviert; Node,
Drive/MAM, Profil, native Kapazität, Label und Medienklasse sind versiegelt.
Die Schreibanforderung akzeptiert keine neuen Metadaten. Native Kapazität stammt
aus einem bestätigten Profil (hier LTO-4: 800.000.000.000 Byte); unbekannte Dichte
oder Profile werden ohne Annahmen abgewiesen. Vor Gerätezugriff wird der Grant
verbraucht, danach Hardware frisch erkannt und unter I/O-/Laufwerkssperre erneut
geprüft. Lokale bekannte Kassetten sämtlicher Klassen und Zustände sowie
ungeklärte Writes/Initialisierungsintents bleiben gesperrt. Dies ist kein
Recyclingworkflow. Lokal unbekannt bedeutet nicht leer: Der Review warnt vor
Verlust aller unbekannten vorhandenen Inhalte und verweist bei Katalogverlust
auf lesende Registrierung/Rekonstruktion.

Der bestehende LinuxTape-Kern bestätigt BOT, schreibt den lokalen vollständigen
Header mit dauerhaftem Pending und prüft Dateimarke, Dateianzahl, Inhalt und
vollständigen physischen Header-SHA-256. Erst danach werden UUID, MAM-Seriennummer,
native Kapazität und Drive-Bindung registriert. INITIALIZED bestätigt nur den
Header, keine Datenarchive oder Vollqualifikation. Nach einem möglichen Write
bleibt die Kassette auch bei Fehler der Katalogpublikation reserviert; kein
automatisches erneutes Formatieren oder Entfernen von Markern.

**198 lokale Tests (ein Skip) und 198/198 Debian-Tests** unter
`/var/lib/otam/acceptance-code/physical-initialization-20261020` bestanden.
JavaScript-Syntaxprüfungen und Harness-Syntaxprüfung bestanden. Zusätzliche
Tests prüfen Native-Kapazitätsherkunft, bekannte Medien inklusive ARCHIVED/RETIRED,
Default-Gate, Admin/CSRF, Einmaligkeit bei mehreren vorbereiteten Grants, Ablauf,
veränderte Reviewdaten, falsches Medium, Pending-Symlink, erhaltene Reservation
nach tatsächlichem Ende eines Softwareprozesses, falschen Header und fehlgeschlagene
Katalogpublikation. Die LinuxTape-Dateigeräteprüfung umfasst den regulären
Initialisierungs-Workerpfad mit Header-Readback und anschließendem Archivieren/
Restore. Der neue Abnahmeharness wurde ebenfalls hinter dem Dateigerät geprüft:
ein Headerread an Position 0, kein Append und unveränderte installierte Konfiguration.

`tools/tape_initialization_acceptance.py` ist für die reale Headerabnahme
vorbereitet. Er verlangt konkrete Drive-/MAM-Seriennummern und die exakte
destruktive Bestätigung, verwendet Live-Katalog/Control/Locks/Pending zur
dauerhaften Sichtbarkeit von Unsicherheit und erhält alle vorhandenen
Archivdatensätze. Gates werden nur im Speicher des Kandidaten aktiviert.
Der Hauptworker muss für die kurze Hardwareunit kontrolliert angehalten und
nach ihrem Ende über OnSuccess/OnFailure wieder gestartet werden.

Es wurde **keine reale Initialisierung gestartet**. Die bisherige Testkassette
ist bereits katalogisiert und bleibt unverändert. Für den nächsten Nachweis wird
eine zweite konkret identifizierte Testkassette benötigt, deren vollständiger
Inhaltsverlust ausdrücklich freigegeben werden muss. Zunächst nur lesend
identifizieren; keine unbekannte Kassette eigenmächtig beschreiben. Danach
bleiben reale Mehrbandwechsel und abschließend der kleine Schreibabbruch/Tail-
Neustartnachweis offen. [Ablauf und Grenzen](architecture/physical-initialization.md).


### Zweite Kassette: reale Initialisierung bestanden

Nach ausdrücklicher Freigabe der eingelegten zweiten Testkassette wurde deren
MAM-Identität frisch als `HC4AS6a414` im bekannten Laufwerk `1K10112224` erkannt.
Bestätigtes LTO-4-Profil, native Kapazität 800.000.000.000 Byte, bereit und
nicht schreibgeschützt. `otam-physical-initialization-second.service` hat mit
dem zuvor unter Debian vollständig geprüften Initialisierungskandidaten den
normalen Initialisierungs-Workerhandler ausgeführt. Ausschließlich Laufzeitflags
im Abnahmeprozess waren aktiviert; installierte Konfiguration und Gates sind
unverändert. Live-Katalog, Control, Laufwerkssperren und Pending-Journal wurden
verwendet. Der Hauptworker war kontrolliert gestoppt und wurde über OnSuccess
wieder gestartet; Web und Katalogtunnel blieben aktiv.

**Ergebnis: Headerinitialisierung bestanden, INITIALIZED.** Bestätigt sind
BOT, geschriebener Header, Dateimarke, Bandende mit einer Banddatei und genau
eine vollständige physische Headerrücklesung. SHA-256:
`9e831c319d23a20a584282d5f3263c15eaea85ce60195ffe48f1ebfc1fc94594`.
Neue Medien-UUID: `4c7a70fe-f1a4-45f9-b14c-02cfaf1c9896`, Klasse Rotation.
Die acht bisherigen Archivdatensätze wurden unverändert erhalten. Kein
Datenarchiv wurde als VERIFIED erzeugt; dies ist keine Vollqualifikation dieser
zweiten Kassette. Originalbericht:
`/var/lib/otam/reports/physical-initialization-second-20261020-r1/report.json`.
Der Rohbericht ist nur im ignorierten lokalen Dossier samt SHA256SUMS gesichert.

Für den folgenden kleinen Wechseltest werden zwei normale, ausdrücklich je
Medium geplante Kindaufträge zu einem Abnahme-Parent verbunden. Keine native
Kapazität und kein Verbrauchswert wird verändert, keine Hunderte GB für einen
künstlichen Platzmangel geschrieben. Dieser Test weist den realen Wechselpfad,
WAITING_MEDIA, vollständigen Readback und Restore beider Kinder nach; die
automatische Kapazitätsverteilung bleibt durch gesonderte Softwaretests belegt.
Der tatsächliche Schreibabbruch/Tail-/Neustartnachweis bleibt zuletzt offen.
**Keine Produktionsfreigabe und kein Deployment.**

Der neue `tools/tape_exchange_acceptance.py`-Kandidat besteht **199/199 Debian-
Tests** (lokal 199 mit einem Skip); die abschließende strengere Kontrolle der
Transfer-Samples wurde zusätzlich im vollständigen Harness-Dateigerätetest
unter Debian geprüft. Der Dateigerätetest durchläuft Prepare, explizite kleine
Kindpläne, Staging, einen abgewiesenen falschen Medienwechsel ohne Write, beide
Backup-Set-Schritte, WAITING_MEDIA/VERIFIED und verifizierte Restores. Native
Kapazitäten bleiben jeweils 800.000.000.000 Byte. Livekonfiguration und
Transfer-Einstellungen bleiben unverändert; Abnahmewerte liegen in privater
Test-Control. Adapter erhalten hingegen immer den **Live-State** für sämtliche
Laufwerkssperren, Pending-Marker und Transferlogs. Archivmetadaten werden direkt
im Livekatalog geführt, statt später Vollrekonstruktionen zu benötigen.

Der erste reale Schritt wurde als `otam-physical-exchange-first.service` mit
Code unter `/var/lib/otam/acceptance-code/physical-exchange-20261020` gestartet.
Er bereitet genau zwei eigene 1-MiB-Quelldateien vor, plant pro Medium ein TAR,
staget beide auf der qualifizierten HDD und bearbeitet zuerst die zweite
Kassette. Report: `/var/lib/otam/reports/physical-exchange-20261020-r1/report.json`.
OnSuccess/OnFailure startet den zuvor kontrolliert angehaltenen Hauptworker
wieder. Keine parallelen Gerätejobs oder Änderung des laufenden Kandidaten.

Der erste Wechselharness-Aufruf `otam-physical-exchange-first.service` wurde
vor Planung, Staging und sämtlichen Bandzugriffen sicher abgewiesen: Die
Live-Control enthielt nur die gerade initialisierte neue Medienbindung. Der
frühere HTTP-/CLI-Abnahmelauf hatte die Bindung der ersten Kassette in seiner
isolierten Control bestätigt, beim Metadatenimport aber nicht übernommen.
Der historische Journalfehler bleibt lokal unverändert erhalten. Die
bereits physisch nachgewiesene Bindung wurde anschließend aus genau dessen
VERIFIED-Report (`00797008418f086c6c5d78d0987c913bc23cf3c0abb5d57041e9a31c6889623e`)
und Control übernommen: exakte UUID/MAM/Drive-Zuordnung, passender physischer
Live-Header und acht VERIFIED-Archive wurden geprüft. Kein neues Erkennen
oder Lesen des aktuell nicht eingelegten alten Mediums wird damit behauptet;
der obligatorische frische Identitäts-/EOD-/Receipt-Check vor Write bleibt
bestehen. Herkunft wurde in der Live-Control auditiert und als Konfigurations-
ereignis protokolliert.

Der neue, ausdrücklich nach dieser Ursachenprüfung gestartete Lauf heißt
`otam-physical-exchange-first-r2.service`, Reportroot
`/var/lib/otam/reports/physical-exchange-20261020-r2`. Der ursprüngliche
Reportroot r1 wird nicht wiederverwendet. Keine Schutzprüfung wurde gelockert.

#### Medienwechsel, erster realer Kindauftrag bestanden

`otam-physical-exchange-first-r2.service` ist erfolgreich beendet. Der erste
Kindauftrag auf der neu initialisierten Kassette ist VERIFIED, der Parent
`58f57007-ab95-4bda-b8b1-830cb4182184` korrekt **WAITING_MEDIA**, nächstes Medium
die erste Testkassette. Neues TAR an Position 1 und Receipt an 2; genau ein
Payloadread während Backup und ein weiterer während Restore. Keine alten
Nutzdaten wurden gelesen. TAR-Größe 1.054.720 Byte, SHA-256
`ec331f53b4daefa02f9efeec2bced6ba95aaca07577db61b27e2dc6770666c4e`.
Ein eigener 1-MiB-Inhalt wurde wiederhergestellt. Quelle und Ziel wurden nach
Ende der Unit nochmals unabhängig gehasht: jeweils
`b3598e14b07eb4f83ee4ad037a28657a3acc6c5adb9f9c8d53e8044aa4d5e227`.
Zwei tatsächliche Schreib-Samples bestätigen 120.000.000 Byte/s Hostlimit,
2.483.027.968 Pufferbytes und 90 Prozent Vorfüllung. Für ein so kleines TAR
liegen keine belastbaren Füllstands-/Dauerratenmessungen vor; dafür bleibt der
große bereits bestandene Zyklus maßgeblich.

Der Livekatalog enthält nun neun VERIFIED-Archive. Die bisherigen acht
Datensätze sind unverändert. Worker, Web und Tunnel sind wieder aktiv. Der
zweite Kindauftrag ist vollständig lokal gestaged und wartet auf den
physischen Rückwechsel zu `HC4BELa904`. Der Medienwechsel ist erst nach dessen
frischer Identitätsprüfung, normalem Backup-Set-Schritt und Restore vollständig
abgenommen. Keine Produktionsfreigabe. Alle Quellen und Testausgaben bleiben
erhalten; kein weiterer großer Restore.

#### Kleiner realer Medienwechsel vollständig bestanden

`otam-physical-exchange-second.service` endete erfolgreich am 20.10.2026
um 17:09:52 MESZ. Parent `58f57007-ab95-4bda-b8b1-830cb4182184` ist
**VERIFIED**, beide Kinder und beide Restores sind VERIFIED, kein nächstes
Medium wird angefordert. Der zweite Schritt schrieb ausschließlich TAR 17
und Receipt 18 auf der ersten Kassette. Nutzdatenposition 17 wurde genau
einmal während Backup und einmal während Restore gelesen. Alte große
Nutzarchive wurden nicht an den Host gelesen; physisches Vorwärtspositionieren
zu den vorausgehenden Receipts blieb erforderlich.

Das zweite TAR hat 1.054.720 Byte und SHA-256
`958bb37d290f3c3c6c10fe9170b3a8b1f9b9d24b5b9a3a44236dbc88ccfe9b46`.
Quell- und Zieldatei wurden nach Testende nochmals unabhängig geprüft:
`545e8527cf9ef2d2d75d57d4019519de21073754111165ac67fc34ffe3df944c`.
Auch die erste wiederhergestellte Datei wurde erneut unabhängig bestätigt.
Zwei neue echte Schreib-Samples bestätigen 120.000.000 Byte/s Hostlimit,
2.483.027.968 Pufferbytes und P90. Wegen der kleinen TARs wird keine neue
Dauerdurchsatz- oder Pufferfüllstandsqualifikation daraus abgeleitet.

Livekatalog: zehn VERIFIED-Archive, die acht alten Archivdatensätze
unverändert. Worker, Web und Tunnel sind aktiv; Katalogsync bestätigt
Sequenz 174 mit UNCHANGED. Report
`/var/lib/otam/reports/physical-exchange-20261020-r2/report.json`, SHA-256
`06359d721ed234ae5938ad592e3ec0d5772d14c0b527ca58cf8d0f2b53387fcd`. Lokale Rohdaten/Journale mit
SHA256SUMS sind vom Upload ausgeschlossen. Quellen und Restore-Ausgaben
bleiben erhalten.

Diese Abnahme bestätigt den echten Wechsel zwischen zwei ausdrücklich
zugeordneten kleinen Kindaufträgen. Sie behauptet keinen physisch erzwungenen
Kapazitätsüberlauf; automatische Kapazitätsverteilung ist separat softwaregeprüft.
Die installierte Version und Gates bleiben unverändert. Offen sind der
tatsächliche kleine Schreibabbruch mit dauerhaftem Pending und Neustart-/
Tail-Sperre sowie die abschließende geprüfte Installation und Betriebsaktivierung.
**Weiterhin keine Produktionsfreigabe.**

### Schlussabnahme: echter kleiner Schreibabbruch gestartet

Der Benutzer hat die selbstständigen letzten Schritte bis zur Freigabe und
anschließende Bereinigung der Testmedien/-dateien im Katalog autorisiert.
Vor jeder Bereinigung werden Katalog und Control unabhängig gesichert; Quellen,
Staging-Artefakte, Hardwareberichte und dauerhafte Pending-Journale werden dabei
nicht gelöscht. Staging-Qualifikation, Konten und Konfiguration bleiben erhalten.

`tools/tape_interrupt_acceptance.py` bestand vier zusätzliche Softwaretests,
darunter ein tatsächlich abrupt beendeter Softwareprozess nach dem ersten
geschriebenen Dateiblock, unverändertes Journal, Ablehnung fehlender/verlinkter
Marker und eine frische LinuxTape-Instanz ohne weitere Bewegungen/Writer.
Der eingefrorene Kandidat unter
`/var/lib/otam/acceptance-code/physical-interruption-20261020` bestand alle
**203/203 Debian-Tests**. Dies allein ist kein physischer Abbruchnachweis.

Die reale Unit `otam-physical-interruption.service` wurde am 20.10.2026 um
17:32:55 MESZ mit bestätigtem Drive/MAM und leerer Queue gestartet. Sie verwendet
den normalen Archivierungs-/Staging-/LinuxTape-Pfad und ein eigenes 8-MiB-TAR.
Nach dem ersten akzeptierten 512-KiB-Record beendet sich ausschließlich der
Testwriter abrupt. Der Supervisor begrenzt dessen eigene Prozessgruppe und
prüft anschließend mit frischen CLI-/Backend-Prozessen Job-/Archiv-/Staging-
Zustände, erhaltene Quelle und Staging, dauerhaftes Live-Pending und Ablehnung
weiteren Schreibens vor Header/EOD/BOT/Writer. Dies ist ein Prozessabbruchtest,
kein Stromausfalltest. Kein blindes Wiederholen bei unerwartetem Ergebnis.

Live-Katalog, Gerätesperren und Pending-Journal bleiben maßgeblich. Hauptworker
ist währenddessen kontrolliert angehalten; OnSuccess/OnFailure startet ihn
wieder. Web und Tunnel bleiben aktiv. Report:
`/var/lib/otam/reports/physical-interruption-20261020-r1/report.json`.
Installierte Version/Gates sind unverändert. **Bis zum belegten Abschluss
weiterhin keine Produktionsfreigabe und keine Katalogbereinigung.**

Der anschließende Release-Kandidat 0.6.0 sowie die ausdrücklich ID-begrenzte,
transaktionale Katalogbereinigung bestehen lokal **207 Tests mit einem Skip**.
Die Bereinigung verlangt den exakten Reviewhash des vollständigen Katalogstands,
verweigert unbekannte IDs, aktive Jobs, geänderte Katalogstände und Beziehungen
über die ausgewählten Grenzen hinaus. Fehler rollen alle Löschungen zurück.
Dazu kommen vier gezielte SQLite-Tests. Ein Offline-Wheel wurde gebaut; dieser
neue Kandidat ist noch nicht unter Debian vollständig geprüft oder installiert.

#### Echter physischer Schreibabbruch bestanden

Die Unit ist erfolgreich beendet; Abnahmebericht **VERIFIED**. Der normale
LinuxTape-Pfad hat genau den ersten 512-KiB-Record des eigenen vollständigen
8-MiB-Staging-TARs angenommen, danach endete der Writerprozess per `os._exit(79)`.
Die eigene Producer-Prozessgruppe wurde begrenzt. Ein frischer CLI-Workerprozess
markierte Job INTERRUPTED, Archiv INCOMPLETE, Staging INTERRUPTED und Medium
SUSPECT. Ein weiterer frischer Backendprozess verweigerte Append aufgrund des
erhaltenen Live-Pending vor Header, EOD/BOT, Reader oder Writer; nur die normale
Identitätsprüfung und akzeptierte Blockmodusprüfung im Lock wurden ausgeführt.

Quelle, vollständiges lokales Staging-TAR und alle vorherigen Archivdatensätze
blieben unverändert. Das dauerhafte Pending hat weiterhin SHA-256
`699ca7db32fa213289ab1f71f2a657d002d24936d19a4cc72cd764ab7a731ef5`.
Es wurde keine automatische Markerbereinigung, Wiederaufnahme, Neuinitialisierung
oder weitere Vollprüfung ausgeführt. Dieser Nachweis simuliert Prozessverlust,
keinen Stromausfall und keine Zusicherung über noch nicht verifizierte Nutzdaten.

Die Kassette bleibt bewusst mit unsicherem Tail gesperrt. Das Sperrjournal muss
auch bei der ausdrücklich autorisierten Testkatalogbereinigung erhalten bleiben.
Worker, Web und Tunnel sind nach Testende wieder aktiv. Der nächste Schritt ist
die abschließende Debian-Prüfung des 0.6.0-Pakets, geprüfte Installation,
Betriebsprüfung und gezielte Katalogbereinigung mit vorherigen SQLite-Backups.
**Noch keine abgeschlossene Betriebsfreigabe.**

### Abschließende Installation und Betriebsfreigabe 0.6.0

Der abschließende Kandidat bestand **207/207 Debian-Tests** und lokal 207 mit
einem Skip. JavaScript-Syntax und 44 Webtests bestanden. Offline-Wheel:
`opentape_archive_manager-0.6.0-py3-none-any.whl`, SHA-256
`2a5f0395dbf154c86d8d5e32088aed632b57f0f66730651ea948f158654a5f68`.
Die installierte Version wurde anschließend mit dem isolierten Interpreter
bestätigt: 0.6.0 aus der tatsächlichen Dienstumgebung.

Die erste Paketinstallation offenbarte einen historischen `pip`-Launcher mit
Shebang auf eine frühere verschobene venv. Der Import-Versionscheck erkannte
den alten Modulstand vor Aktivierung. Installation über den ausdrücklich
gewählten Interpreter `python -m pip` korrigierte dies; aktive pip-/otam-
Launcher verweisen jetzt auf `/opt/otam/venv/bin/python`. Keine Bandaktion
fand während der Installation statt; Web und Worker waren angehalten.

Vor der gezielten Bereinigung wurden konsistente SQLite-Backups beider
Datenbanken, Konfiguration und Pending-Journal privat gesichert. Die exakte
ID-Liste und der vollständige Katalog-Reviewhash wurden geprüft. Entfernt:
3 Medien, 11 Archive, 15 Dateieinträge, 11 zugehörige Jobs; Verknüpfungen
transaktional entfernt und Foreign Keys/SQLite-Integrität geprüft. Drei
Staging-Benchmarkberichte und deren Jobs bleiben für die Qualifikation erhalten;
ein separates Bereinigungs-Audit ist vorhanden. Kein Quell-/Restore-/Staging-
Artefakt und kein Bandinhalt wurde dadurch gelöscht. Das Live-Pending und die
verbrauchte Initialisierungsreservation bleiben erhalten.

Die Live-HTTP-Prüfung bestätigte 0.6.0 und aktivierte getrennte Hardware-Gates,
physischen Modus, genau ein HDD-Staging, leere Medien-/Dateisuche, Adminverwaltung,
401 ohne Anmeldung sowie CSRF-, Origin- und Host-Sperren. DE/EN-Umschaltung und
Rückstellung der ursprünglichen Kontosprache bestanden. Admin-Shutdown-Status
wurde nur lesend geprüft, kein Shutdown ausgelöst. Alle referenzierten UI-Assets
antworten erfolgreich. Der erste HTTP-Harness erwartete irrtümlich `/static/`
statt der im HTML angegebenen `/assets/`-Routen; dieser historische Prüfbericht
bleibt erhalten. Der korrigierte vollständige Nachtest endete VERIFIED.

Web, Worker und SSH-Katalogtunnel laufen; Worker-Heartbeat ist aktuell. Der
bereinigte Katalog wurde signiert an den optionalen Katalogdienst übertragen:
Sequenz **180 SUCCEEDED**, anschließender expliziter normaler Worker-Sync
**SUCCEEDED/UNCHANGED** mit bestätigter Sequenz 180. Der Replikationszähler wurde
nicht zurückgesetzt.

**Freigabeumfang:** reguläre Dateien auf dem abgenommenen IBM-HH4/LTO-4-Profil,
qualifiziertes lokales Staging, bestätigte Einzel-/Mehrbandjobs, vollständiger
SHA-256-Readback, selektiver Restore und optional replizierter Katalog. Andere
Laufwerksprofile benötigen eigene Hardwareabnahme. Vollständige Systemstände
mit ACL/xattrs/Links, automatische Rotation/Recycling bekannter Medien und
Verschlüsselung sind weiterhin spätere Funktionen; NAS-Backup bleibt optional
und benötigt ein konfiguriertes Ziel. Die neue Kassette wurde hier nur im
Header-/Kleinarchivzyklus geprüft, nicht vollqualifiziert.

**Kein weiterer unbeaufsichtigter Test ist notwendig.** Die eingelegte
Abbruchtestkassette wird nicht wiederverwendet oder automatisch entsperrt.
Für produktive Daten ein geeignetes Medium über den normalen expliziten
Initialisierungs-/Registrierworkflow bereitstellen. Die abgewählten langen
SMART- und echten Shutdown-Tests wurden nicht ausgeführt.

Nach der Bereinigung wurden beide Initialisierungssperren nochmals ohne
Bandbewegung geprüft: Abbruchmedium durch das unveränderte Live-Pending,
zweites Testmedium durch die erhaltene verbrauchte Initialisierungsreservation.
Der endgültige betriebliche Freigabestatus ist in der Live-Control als READY
mit Version 0.6.0 und den abschließenden Zählern gespeichert.

## 20.10.2026: 0.6.1 – expliziter Abbruch-Reset und Hardwareansicht

0.6.1 wurde nach 218/218 Debian-Tests (isoliertes Test-TMPDIR), 218 lokalen
Tests mit einem Skip und JavaScript-Syntaxprüfung installiert. Neue Tests
prüfen echten Softwareprozessverlust nach Reservation und nach durablem
Journalübergang, Schutz aller katalogisierten Medienklassen/-zustände,
Medienverwechslung, veränderte Reviews, Symlinks, Publikationsfehler und den
regulären Workerzyklus nach Reset einschließlich Archiv-/Restorehashes.
HTTP-Admin-/CSRF-Schutz und verweigerte Operatoraktionen sind abgedeckt.

Der reale, ausdrücklich autorisierte Reset der ehemaligen Abbruchtestkassette
endete VERIFIED nach 18,76 Sekunden. Neues produktives Medium „LTO-4 Archiv 01“,
800.000.000.000 native Bytes, Dauerarchiv, Zustand READY. Genau ein Headerread
an Position 0; Bewegungsbefehle REWIND/EOD/REWIND, keine Nutzdatenreads und
keine erneute Vollqualifikation. Der alte Pending-SHA-256 ist im dauerhaften
Historienjournal unverändert nachgewiesen. Der neue Guard wurde erst nach
Headerprüfung, Katalogpublikation und Bindung abgeschlossen. Reales Testband B
blieb unverändert. Dies ist logische Neuinitialisierung, kein sicheres Löschen.

Bericht: `/var/lib/otam/reports/physical-reset-061-20261020-r1/report.json`,
SHA-256 `ad753dac8f43b6dbc52aa05f94cbf2509fed7e2bd4bd84ad06e906109eb25c57`.
Finales Wheel-SHA-256:
`8519c394c50804b6c48173decf73f354ca8d2b685e1dc0e57c46230e993f7d2f`.
Guardfähige Version wurde vor dem Reset installiert; keine Rückkehr zu alten
Workern während eines ungeklärten Reset-Guards. Reset-Flag nach physischer
Abnahme aktiviert. Live-HTTP prüfte Authentifizierung, Version/Gates,
ausgelieferte Karten/CSS und Resetdialog, lesende Planbarkeit und Katalog:
ein READY-Medium, null Archive und null Dateieinträge. Web, Worker und Tunnel
aktiv; signierter Peerstand Sequenz 196 bestätigt (UNCHANGED beim expliziten
Nachlauf). Vorherige SQLite-/Konfigurations-/Pending-Backups separat erhalten.

Hardwareaktionen stehen jetzt in umbruchfähigen Gruppen; destruktive Bandpflege
ist aufklappbar. Die API liefert den tatsächlichen Initialisierungssperrgrund.
Nach Medienwechsel gilt eine Diagnose anderer MAM nicht als aktuelle Messung.
Aktuell keine TapeAlert-Flags; ein historischer Hinweis bleibt ausdrücklich als
Verlauf erhalten. Ein ausgewähltes Zielmedium ist für das bestehende TAR-Format
nötig, muss für Planung/Staging aber nicht eingelegt sein. Medienunabhängiges
Vorstaging ist nicht implementiert.

## 20.10.2026: Kandidat 0.6.2 – abgeschlossene Initialisierung ersetzen

Noch **nicht installiert oder physisch freigegeben**. Der laufende Produktivstand
bleibt 0.6.1 mit READY-Medium „LTO-4 Archiv 01“. Ein während der Entwicklung
laufender Benutzer-Planungsauftrag wurde nicht unterbrochen.

Die zweite, aus dem Testkatalog entfernte Kassette ist durch ihren erhaltenen
SUCCEEDED-Initialisierungsbeleg geschützt, nicht durch einen aktiven TapeAlert.
Der Kandidat bietet einen eigenen default-false Neuinitialisierungsworkflow,
klare Medien-ID-/Zeitangabe und getrennte Wahl zwischen lesender Registrierung
und destruktiver Neuinitialisierung. Ein beliebiges force-Flag gibt es nicht.
Nur abgeschlossene Vorgänger ohne aktuelle physische Katalogbindung sind
zulässig; Pending, Reset-Guards und unklare Schreibintents bleiben gesperrt.
Explizite Simulator-Katalogeinträge mit gleichem Label/Serienfeld blockieren keine
physische MAM. Der vorhandene echte Header muss zur letzten erfolgreichen UUID
passen, bevor der normale geprüfte Initialisierungspfad schreiben darf.

226/226 Debian-Tests bestanden; lokal 226 mit einem Skip. Nach zusätzlicher
Header-UUID-Prüfung acht gezielte Neuinitialisierungs-/Harness-Tests lokal und
unter Debian bestanden. Die Header-only-Hardwareharness ist mit dem echten
LinuxTape-/Workerhandler hinter FileST geprüft: alter Header und neuer Header
je einmal gelesen, unveränderte Node-Konfiguration und alte Freigabebelege,
keine Nutzdatenreads. JavaScript-Syntax und Hardwareansicht im Browser geprüft.
Die reale Belegprüfung der zweiten Kassette bleibt offen und benötigt deren
bestätigtes Einlegen bei freiem Laufwerk. Kein Bandwrite dieses Kandidaten
wurde durchgeführt; die erste produktive Kassette bleibt unangetastet.

## 20.10.2026: zweite Produktivkassette und Quellenplanung vor Medienauswahl

Der Benutzer bestätigte den Abbruch der zu großen Einbandplanung. Vor dem
Beenden wurde der reine INVENTORY-Zustand bei angehaltenem Prozess erneut
geprüft: genau ein Planungsauftrag, keine schreibenden Archive, keine offenen
Bandgeräte und keine Kindprozesse. Nur dieser lesende Prozess wurde beendet;
SQLite-Zustände wurden unter Worker-/I/O-Sperre konsolidiert, Quellen und Band
blieben unverändert. Bericht: `usb-single-plan-cancel-20261020-r1/report.json`.

Die reale Neuinitialisierung der zweiten freigegebenen Kassette scheiterte im
0.6.2-Nachweis sicher vor jedem Write: bestätigtes EOD mit null logischen
Banddateien statt des alten Headers. `write_attempted=false`; ursprünglicher
Report/Grant unverändert erhalten. 0.6.3 ergänzt den ausdrücklich bestätigten
Null-Datei-EOD-Fall, ohne ungeklärte Intents zu übergehen. 228 Debian-Tests und
neun gezielte Neuinitialisierungstests bestanden. Neuer separater Hardwarelauf
`physical-reinitialization-063-20261020-r1/report.json` endete VERIFIED: vorher
null Banddateien, genau ein vollständiger neuer Headerread an Position 0,
keine Nutzdatenreads. Produktivmedium „LTO-4 Archiv 02“, 800.000.000.000 native
Bytes, Dauerarchiv, READY. „LTO-4 Archiv 01“ blieb unverändert. Beide stehen im
Produktivkatalog; keine Testarchive oder Testdateien wurden wieder importiert.

0.7.0 führt den Quellenplan vor Medienzuordnung ein; 235 Debian-Tests bestanden,
nach letzten kleinen Validierungskorrekturen sieben gezielte Debian-Tests erneut
bestanden. Der echte lokale Browser-/HTTP-/Workerablauf mit getrennten synthetischen
Fixtures bestätigt: ohne Medium Größenplan erstellen, mit einer zu kleinen
Medienauswahl den gleichen Quellenplan behalten und mit einem zweiten Medium
den verbindlichen Mehrbandplan erstellen. Keine Geräteaktionen in diesem UI-Test.
Auch der bisherige direkte Planungsaufruf prüft Größen/Kapazität vor Hashberechnung.

Bei der root-Paketinstallation wurde versehentlich Umask 0077 auf Programmdateien
übertragen. Web/Worker starteten dadurch vorübergehend nicht. Korrektur auf
Programmverzeichnisse 0755/Dateien 0644, Import als Dienstkonto und Live-HTTP
geprüft; private Konfiguration/Journale behalten restriktive Rechte. Der erste
Live-HTTP-Versuch scheiterte vor Einreihung eines Auftrags; separates Outcome
unter `source-first-070-live-20261020-r1/` erhalten. Installation verlangt künftig
Umask 0022 und einen Importcheck als `otam` vor Aktivierung.

Der anschließende schnelle Quellenplan stieß vor Inhaltslesung auf externe
Symlinks in `LP Archiv/.@__thumb`. Auswahl war bislang die gesamte USB-Platte.
Der Benutzer autorisierte ausdrücklich nur `LP Archiv`, ohne diesen
NAS-Vorschaubereich. 0.7.1 ergänzt versiegelte exakte `excluded_paths` in
Quellenplan, Hashberechnung, verbindlichen Kindplänen und Staging. Keine Links
werden stillschweigend verfolgt oder ausgelassen; der konkrete Ausschluss ist
in der Oberfläche sichtbar. Der unveränderte ursprüngliche Fehlversuch bleibt
als Beleg erhalten. Details und Grenzen: [Quellenplanung](architecture/source-first-planning.md).


0.7.1 ist nach 237/237 Debian-Tests und 237 lokalen Tests mit einem Skip
installiert. Ein zuvor veränderter Symlink-Exceptiontyp wurde während der
Regressionstests erkannt und vor Freigabe kompatibel korrigiert; 52 gezielte
Workflow-/Quellenplantests sowie anschließend alle 237 Tests unter Debian
bestanden. Der zusätzliche Ausschlusstest bindet denselben Quellenplan und
führt echtes lokales TAR-Staging mit ausschließlich den freigegebenen regulären
Dateien aus; die externen Vorschaulinks werden nicht geöffnet. Im Produktivsystem
wird der neue LP-Quellenplan mit der ausdrücklich bestätigten Auswahl aufgebaut,
noch ohne Medienzuordnung und ohne Inhalts-/Band-I/O. Kein großer Bandtest wurde
für diese Änderung wiederholt. Der vollständige physische Kernnachweis der
vorherigen Freigabe bleibt erhalten.


### 0.7.2: lineare Gruppierung und echter LP-Quellenplan

Die echte Quelle hat 30.800 Dateien. Die bisherige TAR-Gruppierung berechnete
beim Hinzufügen jeder Datei die komplette bisherige Gruppe neu und verursachte
quadratische CPU-Arbeit. Der eigene reine Metadatenlauf wurde nach erneuter
Prüfung ohne Bandgeräte/Kindprozesse beendet; Quellen unverändert. Die Gruppierung
zählt jetzt den exakt gleichen JSON-/TAR-Schätzbedarf einmal je Eintrag, inklusive
UTF-8, Listenklammern und Kommas. Ein Grenzwerttest und 2.000 Einträge prüfen
identische Größenbedingungen sowie lineare Serialisierungsarbeit. 53 gezielte
Workflow-/Quellenplantests und anschließend 238/238 Debian-Tests bestanden.
Lokal 238 mit einem Skip; JS-Syntax bestanden. 0.7.2 ist installiert, Import vor
Dienststart als `otam` bestätigt, Web/Worker/Tunnel aktiv.

Der echte neue Quellenplan für ausschließlich `LP Archiv`, ohne
`LP Archiv/.@__thumb`, endete nach 11,59 Sekunden erfolgreich in WAITING_MEDIA:
30.800 Dateien, 1.522.565.501.226 Nutzbytes, 17 TARs, konservativer Gesamtbedarf
1.522.733.735.390 Byte. Größtes vollständiges TAR 388.772.424.710 Byte; einzelne
Dateien werden nicht geteilt. Keine Dateihashes, kein Staging-TAR, kein Band-I/O.
Mit 95-Prozent-Grenze und der bestehenden TAR-Reihenfolge werden drei frische
LTO-4-Medien projektiert. Zwei vorhandene READY-Medien sind dafür nicht genug;
Reserve wurde nicht gelockert. Der Plan wartet dauerhaft auf Medienzuordnung.
Bericht: `/var/lib/otam/reports/source-first-072-live-20261020-r1/report.json`.

Der reale Kapazitätscheck mit beiden vorhandenen Produktivmedien endete erfolgreich
mit Ergebnis WAITING_MEDIA: verfügbar 1.519.999.979.520 Byte, Bedarf
1.522.733.735.390 Byte. Quellenplan-SHA-256 unverändert, keine Archive/Dateireihen
angelegt und keine Inhaltslesung gestartet. Der unveränderte Quellenplan lässt
weitere Medien zu. Signierter Peer-Katalog Sequenz 203 (17.600.512 Byte) bestätigt,
`peer_updated=true`. Wheel-SHA-256 0.7.2:
`0846901415255e64e7a6879ab7e0ce6155e253676c07b4dbd6859828de8379cf`.
Alle Rohberichte, historische Fehlversuche, Testergebnisse und Syncbelege lokal
ignoriert mit SHA256SUMS gesichert; keine Rohdaten im Git-Upload.

## 0.7.3: native Kapazität ohne feste Prozentreserve

Die pauschale 5-%-Grenze war eine Softwarevorgabe ohne gerätespezifischen
Nachweis. Sie entfällt konsistent in Quellen-/Ein-/Mehrbandplanung, Webanzeige,
Service-Schreibvorprüfung und LinuxTape. Native Kapazität bleibt Obergrenze;
Komprimierungsgewinne werden nicht geplant. Konservative TAR-/Metadaten- und
Receiptabschätzungen sowie echte frühe EOM-/Pending-/Tail-Sperren bleiben erhalten.
Eine gemeinsame Largest-first/Best-fit-Heuristik verteilt vollständige TARs,
mit bisheriger geordneter Zuordnung als Rückfall. Kein mathematischer
Optimalitätsanspruch; pro Kassette bleibt die ursprüngliche TAR-Reihenfolge.

242/242 Debian-Tests in 71,441 s bestanden; lokal 242 mit einem Skip,
JavaScript-Syntax geprüft. Neue Tests prüfen native Grenze, zu große TARs,
Umverteilung ohne unnötiges drittes Medium, den konkreten LP-Schätzbedarf und
reguläre Quellenbindung/Staging oberhalb der alten 95-%-Grenze. Der erste
Debianlauf enthielt versehentlich keine tools-Testhilfen; sein unveränderter
Fehlerbericht bleibt lokal, der vollständige korrigierte Lauf ist bestanden.

0.7.3 wurde nach Leerlaufkontrolle und SQLite-/Konfigurationsbackup installiert;
Dienstkontoimport, Webhealth, Worker und Katalogtunnel sind geprüft. Livekonfiguration,
Quelldaten, Medieninhalte und versiegelter LP-Quellenplan unverändert.
Live-Kapazitätsprüfung ohne Bandaktionen: beide Medien je 799.999.989.760 Byte
frei, TAR-Verteilung 762.465.735.322 / 760.268.000.068 neue Byte; Rest
37.534.254.438 / 39.731.989.692 Byte. Plan weiterhin WAITING_MEDIA, keine
Inhaltshashes berechnet, keine Archive erzeugt. Beide Kassetten können jetzt
zugeordnet werden; Bindung prüft weiterhin Dateifingerprints vor jedem Hash.
Report /var/lib/otam/reports/native-capacity-073-20261020-r1/report.json,
SHA256 735675981b37872fdfca901b465df3a92dfcb3772cce6bea5adb723d68c2217c.
Wheel SHA256 e42caf3ebc1edd33f2fff7ac2c74830b3e5b7e475320541cadea7e22bd8b05ec.
Rohdaten ausschließlich im lokal ignorierten Dossier; kein neuer physischer Test.

## Performance-Update 0.8.0 am Medienwechsel, 21.10.2026

Nach vollständiger Verifikation der sechs TARs auf HC4BELa904 wartete der
Gesamtjob 038ba84f-1596-4829-89d8-c2089b023811 auf Band 2. Queue leer,
keine Live-Pending-/Resetmarker und kein offenes Bandgerät im Worker. Der Nutzer
beauftragte die Optimierung und Installation vor Fortsetzung. Die 0.7.3-
Laufzeitanalyse liegt in architecture/performance-lp-073.md.

Der normale neue archivweise Pfad hat jetzt zwei kombinierte lokale Vollprüfungen
statt acht: einmal vor READY und einmal unmittelbar vor Bandwrite. Archivhash,
TAR/Manifest und Datei-SHA werden jeweils im selben Pass geprüft. Nach dem
vollständigen physischen Readback gegen den unverändert gespeicherten Originalhash
bleibt eine lokale Dateiidentitäts-/Fingerprint-/Schreibschutzprüfung, kein erneuter
lokaler SHA-/TAR-Doppeldurchlauf. Prozessverlust bzw. ältere READY-Artefakte werden
weiter vollständig revalidiert. `create_archive` prüft bei unabhängigen Aufrufern
standardmäßig weiterhin selbst; nur Staging übernimmt die kombinierte Prüfung.

Ein einzelner Reader liest physische Datenrecords in einen begrenzten RAM-Puffer
(maximal 512 MiB, zusätzlich durch verfügbaren Speicher und Profilpuffer begrenzt).
Kleine Metadaten bleiben synchron. Die erste Filemark wird verriegelt; Close wartet
auf das Readerende, bevor Gerätelock oder Positionierung freigegeben werden.
Fehler gelangen zum Prüfer. Archiv-/Datei-/Receiptprüfung bleibt vollständig.
Keine ungeprüfte Geschwindigkeitssteuerung oder Aussage über mechanische
Repositionierungszahlen. Backend-Telemetrie enthält Reader-/Pufferwerte.

Auf der Übersicht steht der aktuelle offene Archivplan mit direkter nächster
Aktion. Joblisten und geöffnete Details zeigen Phasenfortschritt und Prozentwerte,
lokale Prüfungen aktualisieren ihre Zähler. Unbekannte Mengen und wartende Jobs
bekommen keine erfundene Prozentzahl. 100 % Readback bleibt von VERIFIED getrennt.
Bei ausreichend lokalem Platz wird der bestehende `verify_mode=media`-Pfad als
Batchangebot sichtbar. `set-verification-mode` verlangt Plan-ID und aktuellen
Planhash sowie ausdrückliche Bestätigung; ändert ausschließlich noch unbegonnene
Kindpläne und den Parent in einer auditierbaren Transaktion, erzeugt neue
Planhashes und startet keinen Bandwrite. Bereits verifizierte Kindjobs bleiben
bytegleich. Ein alter Bestätigungs-Hash wird anschließend verweigert.

Abnahme:
- 251/251 Debian-Tests in 80,536 s, lokal 251 mit einem Skip bestanden; JavaScript-Syntax und Browserablauf mit isoliertem echten App-/Workerfixture geprüft.
- Neue Softwaretests prüfen zwei statt acht lokale Prüfpasses, lokale Manipulation nach Readback, Prefetch-Reihenfolge, erste Filemark, Fehlerweitergabe, volle Queue und Join vor Freigabe bei laufendem Read. Ein bisheriger Fehlertest verlangte das Wort checksum; die kombinierte Struktur-/Hashfehlerantwort wurde verständlich korrigiert und der Gesamtlauf bestanden.
- Isolierte SQLite-Kopien des echten Katalogs/Control: alle drei LP-Jobs ursprünglich unverändert geladen, Startup-Reconciliation unterbricht keinen davon, nächstes Kind bleibt Band 2. Batchreview nur auf der Kopie bestanden; erstes VERIFIED-Kind und Livejobs unverändert. Keine Quellhashes oder Nutzdaten dafür erneut gelesen. Schema bleibt Version 2, kein Migrationsbedarf.
- Kleiner Header-/Filemark-Hardwaretest auf HC4BELa904 VERIFIED: exakt 10.240 Headerbytes, SHA 7f262a11de664b52b80d5eb14c4fbcd1f02432b53306fd72fef85e5579da9afe, nachher File 1/Block 0, Reader gejoint. Keine Nutzdatenreads und keine Bandwrites. Erster Teststart hatte in seiner Unit die zusätzliche otam-tape-Gruppe vergessen und scheiterte vor Gerätezugriff; r2 verwendete dieselbe Zusatzgruppe wie der reguläre Worker. Historische Reports/Journale erhalten.
- Synthetischer 512-MiB-Stagingvergleich auf der tatsächlichen HDD, jeweils unter MemoryMax=256M zur Begrenzung von Cacheeffekten: 0.7.3 20,959 s / 12,819 CPU-s, 0.8.0 14,452 s / 6,325 CPU-s. Rund 31 % weniger Vorbereitungszeit und 51 % weniger CPU für diese einzelne kleine Messung; kein statistisch abgesicherter Gesamtjob- oder Bandgeschwindigkeitsnachweis. Ein vorheriger 128-MiB-Vergleich mit möglichem Warmcache zeigte 2,105/2,476 s und ist ebenfalls erhalten, nicht als Beschleunigung gewertet.

Wheel SHA256 5e71513f42efd021b756caa80057384f3515d2e8c72892a2f159f61719ab7c9a.
Installation nach erneuter Leerlaufprüfung und Backup
/var/backups/otam/before-performance-080-20261021T164115; pip mit umask 022,
Dienstkontoimport und Health bestanden. Web/Worker/Tunnel aktiv, Konfiguration
und alle drei LP-Jobdatensätze exakt unverändert. Keine Medieninitialisierung,
kein Moduswechsel am Liveplan und kein Start von Band 2 durch die Installation.
Kandidat /var/lib/otam/acceptance-code/performance-080-20261021.
Reports /var/lib/otam/reports/performance-080-20261021-r1/.

Live-Batchangebot für Band 2: 11 TARs, 760.268.000.068 Byte zusätzliche Schätzung
bei 1.715.154.915.328 Byte tatsächlichem Freiraum. Angebot ist möglich, muss aber
noch ausdrücklich gewählt werden; Liveplan weiterhin archive. Weitere 0.8-Wünsche
(Jobnamen, Jobarchiv, Quellenhash-Fortschritt, ETA und empirische Kapazitätsprognosen)
bleiben im Entwicklungsplan offen. 0.8.0 ist das Performance-/Medienwechselupdate,
keine Behauptung einer vollständigen Umsetzung aller dortigen TODOs.
Rohbelege bleiben ausschließlich im lokal ignorierten Hardwaredossier.

Nach Installation blieb die signierte Katalogsynchronisation erfolgreich:
Queueauftrag ef089fb2-c0b8-4749-a765-2b391ad30d39 SUCCEEDED, Ziel UNCHANGED
auf Sequenz 217 (der Katalogstand war bereits veröffentlicht). Der stündliche
Update-Monitor wurde nach erfolgreicher Installation und Nachprüfung beendet.


Abschließender Batch-Nachtrag: Auch der Medienbatch-Pfad verwendet nach
physischer Rücklesung nur die Identitätskontrolle des Staging-TARs, keinen
weiteren vollen lokalen Prüflauf. Er hat damit ebenfalls zwei statt der
bisherigen zahlreichen lokalen Pässe. `scan` erhält einen optionalen
positionsbezogenen Fortschrittscallback: jeder neue TAR-Readback liefert
laufende Bytes/Prozent/Puffertelemetrie, ohne vorherige Nutzdaten zusätzlich zu
lesen. Bereits gelesene TARs bleiben bis zum vollständigen Ketten-/Manifest- und
Hashabgleich PENDING. Ein zusätzlicher Test beweist zwei lokale Pässe und
Rücklesefortschritt für jedes TAR im Batch.

Finaler Stand: 252/252 Debian-Tests in 80,120 s; lokal 252 mit einem Skip in
18,600 s sowie 52 gezielte Batch-/Workflow-/Adaptertests bestanden. Der finale
Kandidat liegt separat unter
/var/lib/otam/acceptance-code/performance-080-final-20261021.
Die identische Prefetch-/Tape-Implementierung behält den obigen Headernachweis;
kein redundanter physischer Test wurde wiederholt. Der echte LP-Katalog wurde
für diesen Stand erneut isoliert geprüft. Nach kontrollierter Aktualisierung
im weiterhin untätigen Medienwechsel sind Konfiguration und alle drei Livejobs
weiter exakt unverändert. Das erste 0.8-Wheel bleibt als Rückweg gesichert;
beide Installationsberichte bleiben erhalten. Finaler Wheel-SHA256:
62479519338f6bfbce7f6e0862480df879df7822d7908cf7a54e4c208f1e5644.
Finale Reports: /var/lib/otam/reports/performance-080-final-20261021-r1/.


## Rücklesekorrektur 0.8.1, 21.10.2026

Der zusätzliche Python-Vorlesethread aus 0.8.0 ist aus dem regulären Lesepfad
entfernt. Vollständige TAR-/Archiv-SHA-/Datei-SHA-Prüfung bleibt synchron im selben
Lesepass; der bewährte 1-MiB-Streambuffer und die erste-Filemark-Sperre bleiben
bestehen. RAM-Messungen auf dem Abnahmeserver: SHA allein 664,5 MB/s, zwei Hashes
331,7 MB/s, vollständiger Prüfer 220,5 MB/s. Mit zusätzlichem Vorlesethread lagen
mehrere Vergleichswerte bei 98–102 MB/s, mit ausschließlich synchronem Pfad in
einem eigenen Folgeprozess 196–218 MB/s bei etwa 2,7 GHz auf dem aktiven Kern.
Gemischte Prozesse zeigten auch synchrone Werte um 120 MB/s. Keine garantierte
physische Bandrate und keine Behauptung gemessener interner Bandbewegungen.
Zeit-/Bytezähler direkt an os.read ermöglichen die weitere Diagnose beim
regulären Band-2-Lauf ohne zusätzliche physische Volltests.

253/253 Debian-Tests in 76,474 s, lokal 253 mit einem Skip in 14,368 s bestanden.
Neue Adapterprüfung belegt vollständigen Bytehash, EOF/Filemark-Latch und
Deskriptorschließung vor der nächsten Geräteaktion. Die isolierte Kopie des
echten LP-Plans besteht erneut Plan-/Modusreview und Erhalt des ersten Kindes.
Schema unverändert. Live-Konfiguration, alle drei Jobdatensätze und Planhash
nach Installation exakt unverändert: erstes Kind VERIFIED (6 Archive), Elternjob
WAITING_MEDIA, zweites Kind PLANNED. Kein Moduswechsel und keine Bandwrites.
Dienste und Healthcheck aktiv.

Kandidat /var/lib/otam/acceptance-code/performance-081-20261021,
Report /var/lib/otam/reports/performance-081-20261021-r1/installation.json.
Backup /var/backups/otam/before-performance-081-20261021T170835.
Wheel-SHA256 700303efdca9f47051a3f80ef820564c0bdd13d9f1c2aee53cd9f77fedb70800.
Installationsvergleich, privater SQLite-/Konfigurationsbackup und Rückweg zu
0.8.0 vorhanden. Rohmessungen und Logs nur lokal ignoriert mit SHA256SUMS.
Signierte Katalogsynchronisation nach dem Update: Auftrag
4bc74ef8-5ad3-4671-824d-0febba43c0c5 SUCCEEDED, Ziel UNCHANGED auf Sequenz 217.


## Batch-Schreibablauf 0.8.2 vor Band 2, 21.10.2026

Alle TARs werden nun nicht nur vorab erstellt, sondern auch vollständig vor dem
allerersten Batch-Write lokal vorvalidiert. Während der Schreibfolge erfolgt
jeweils eine unveränderte Read-only-/Fingerprintkontrolle statt eines weiteren
vollen lokalen Lesepasses. Zwei lokale Prüfpasses pro neuem TAR bleiben bestehen.
Der Backend-Hash des geschriebenen Streams, die Bindung des folgenden Receipts
und die anschließende vollständige physische TAR-/Datei-/Receiptkettenprüfung
bleiben zwingend. Änderungen nach Vorvalidierung blockieren den nächsten Write;
eine fehlgeschlagene letzte Vorvalidierung öffnet überhaupt keinen Bandwriter.

Innerhalb derselben exklusiven LinuxTape-Sitzung wird der durch bestätigte
Filemarks belegte Byteverbrauch fortgeschrieben. Ein neuer/abweichender EOD oder
das Ende der Sperrsitzung verwirft den Verbrauchszwischenspeicher; Pending bleibt
konservativ gesperrt. Der nächste Receipt verwendet den erwarteten Hash des
soeben geschriebenen lokalen Receipts. Das erzeugt keinen Integritätsclaim:
alle neuen Receipts werden erst beim finalen Scan tatsächlich vom Band gelesen.
Die Adapterabnahme zeigt für den zweiten kleinen Batch Writes 5/6/7/8 ohne
Lesegeräteöffnung dazwischen, anschließend echte Adapterreads 5/6/7/8. Frühere
Payloads werden dabei nicht zusätzlich gelesen. EOD-/Identitätsprüfungen,
Filemarks und Prefill bleiben bestehen; kein Versprechen einer mechanisch
unterbrechungsfreien Bewegung. Physische Banddaten wurden für diese Korrektur
nicht zusätzlich gelesen oder geschrieben.

CLI unterstützt den geprüften Queueauftrag set-verification-mode jetzt ebenfalls.
Ungültiger Planhash wird vor Queueeintrag abgewiesen; gültige Prüfung ist
idempotent und ändert vor Ausführung keinen Plan. 259/259 Debian-Tests in
91,776 s; lokal 259 mit einem Skip in 14,770 s bestanden. Reale LP-Katalogkopie
inklusive Modusreview erneut bestanden, erstes Kind exakt unverändert.

0.8.2 wurde mit umask 022 im bestätigten Leerlauf installiert; Dienstkontoimport,
Wheel-Dateivergleich und Healthcheck bestanden. Livekonfiguration, alle drei
Jobdatensätze und Planhash nach Installation exakt unverändert. Band 1 bleibt
mit sechs Archiven VERIFIED, Parent WAITING_MEDIA, Band 2 PLANNED, Modus archive.
Kein automatischer Planwechsel oder Start. Backup:
/var/backups/otam/before-performance-082-20261021T171705.
Kandidat /var/lib/otam/acceptance-code/performance-082-20261021.
Report /var/lib/otam/reports/performance-082-20261021-r1/installation.json.
Wheel-SHA256 5e31e23d917eec704b795d0bcbdb24b494238e4dd4252ddf7f054692048bb55e.
Rückweg zu 0.8.1 vorhanden; Rohlogs und Berichte nur im ignorierten Dossier.
Nachkontrolle: Hardware-scan 0703486c-4a9b-4285-b986-28f9dd976d39 SUCCEEDED,
zuletzt HC4BELa904 im Drive 1K10112224 bereit erkannt. Katalogsync
02cf2e3a-fd74-4cca-8b56-1682ccf80619 SUCCEEDED, signiertes Ziel UNCHANGED,
Sequenz 217. Batchangebot für Band 2: 760.268.000.068 Byte bei
1.715.154.915.328 Byte freiem HDD-Staging. Wechsel auf HC4AS6a414 und explizite
Auswahl/Bestätigung vor dem Start stehen aus.

## Band 2 im bestätigten Batchmodus gestartet, 21.10.2026

Der Nutzer bestätigte ausdrücklich „HC4AS6a414 eingelegt – Batchmodus starten
(empfohlen)“. Frische Worker-Erkennung ac123a18-3bbb-4d56-b863-52eb11bfba4e
SUCCEEDED: Drive 1K10112224, MAM HC4AS6a414, bereit, ungeschützt, passende
Medienbindung 8b4629ab-b17d-4498-8c98-a5582ae68945. Queue war untätig, keine
ungeklärten Pending-/Resetjournale. Der normale CLI-/Workerauftrag
cf1d4ca4-75ce-4f2d-8d09-a5b1e192015f änderte ausschließlich die noch unbegonnene
Etappe auf media und protokollierte die Planrevision. Neuer Parent-Hash:
988462bf3aaf64baf698097eda39bffe3c65fede578b4e84c2e6a1a8d7cb644a.
Erster Kindjob und sämtliche sechs VERIFIED-Archivdatensätze wurden vor/nach
dieser Änderung kanonisch gehasht und sind exakt unverändert.

Der reguläre backup-set-Auftrag bfc09db6-9a21-4926-9012-451972bdfc1b wurde mit
neuem Planhash und resume=false eingereiht und ist RUNNING. Zweiter Kindjob
12ceff77-77ad-4670-b618-3155e191d8d5 ist in STAGING; beim ersten Kontrollsnapshot
631.011.618 von 74.089.667.891 Nutzbytes des ersten TARs vorbereitet. Das ist
kein Fortschrittswert für das gesamte Medium. Alle elf TARs und ihre lokalen
Vorprüfungen kommen vor der Schreibfolge; danach vollständige physische
Rückleseverifikation. Kein weiterer Testlauf oder paralleler Geräteworker.
Startbeleg /var/lib/otam/reports/lp-band2-batch-20261021-r1/start-report.json,
Snapshot lokal ignoriert mit SHA256SUMS gesichert. Dies ist ein laufender
Produktivjob, kein bereits abgeschlossener Verifikationsnachweis.

## LP Archiv abgeschlossen und ausgewertet, 22.10.2026

Der Gesamtjob ist VERIFIED: beide Medien, 17 TARs, 30.800 Dateien,
1.522.565.501.226 Nutzbytes. Band-2-Queue SUCCEEDED, alle elf neuen Archive und
Verifikationen VERIFIED, sämtliche Staging-Cleanups COMPLETE. Abschluss am
22.10.2026 um 03:10:42 MESZ, Laufzeit Band 2 rund 9 h 46 min gegenüber 16 h 25 min
für Band 1 mit ähnlich großer Datenmenge. Erster Kindjob und seine sechs
Archivdatensätze stimmen exakt mit dem Startsnapshot vor Band 2 überein. Das
ist ein Metadatenvergleich, keine erneute physische Rücklesung von Band 1.
Signierter Katalogsync zuletzt Sequenz 233, UNCHANGED.

Die Gesamtlaufzeit sank um 40,45 %, die eigentliche Rücklese-/Prüfrate blieb
jedoch bei rund 53 MB/s. Neue Readerzähler zeigen etwa 1 h 53 min innerhalb der
Geräte-Reads und 2 h 06 min übrige verstrichene Verarbeitungszeit nacheinander.
RAM-Durchsatz allein war damit keine ausreichende Bewertung des vollständigen
Bandpfads. Effiziente Überlappung und geringere Kopierkosten bleiben offen;
keine abgeschwächte Integritätsprüfung oder neue Durchsatzfreigabe behaupten.

Fünf neue USB/UAS-Resets mit Kernel-Lesefehlern auf der Quelle /dev/sdc1 während
der Vorbereitung sind trotz bestandenem SHA-Abgleich zu untersuchen. Die
bekannte Reinigungsaufforderung bleibt bis zum Eintreffen des Reinigungsbands
offen; Nutzer wünschte Reinigung nach Jobende. Für diese Auswertung wurden
weder Banddaten erneut gelesen noch Quellen oder Installation verändert.
Ausführlicher Vergleich und priorisierte Maßnahmen:
[performance-lp-082.md](architecture/performance-lp-082.md).


## Überlappende Bandrücklesung 0.8.3, 22.10.2026

Die Auswertung des abgeschlossenen LP-Jobs zeigte, dass im synchronen Reader
Gerätewartezeit und Prüfung seriell anfallen. Deshalb wurde der zusätzliche
Reader erneut entwickelt und mit realistischen 512-KiB-Records und simulierter
Gerätewartezeit verglichen, nicht nur mit latenzfreiem RAM. Der neue Pfad
übernimmt immutable Records direkt, vermeidet die zusätzliche pro Record
genullte RawIOBase-Zwischenkopie und den äußeren BufferedReader auf dem
Prefetch-Consumer. Genau ein Producer liest voraus, die vollständige TAR-,
Archiv-SHA- und Datei-SHA-Prüfung bleibt im Consumer. Es werden weder alte
Nutzdaten zusätzlich gelesen noch Daten-/Receiptformat oder Verifikationsmodus
verändert.

Daten-TARs verwenden höchstens 64 MiB Queuebudget, weiter begrenzt durch ein
Achtel verfügbaren RAMs und den Profilpuffer; dazu kommen laufende Records und
angeforderte Parserblöcke. Metadaten bleiben synchron. Bei weniger als 16 MiB
Budget, unbekanntem verfügbaren Speicher oder explizitem read_ahead=false bleibt
der synchrone Pfad verfügbar. Erste Filemark dauerhaft gelatcht, Fehler werden
nicht als EOF behandelt, Close wartet auf jeden laufenden Read und den einzigen
Producer, bevor FD/Device freigegeben oder positioniert werden darf. Keine
Änderung an Schreibpuffer, Rate, Prefill, EOD-, Identitäts- oder Pending-Sperren.

Zusätzliche Fortschrittsdaten: Queue-Füllung/Peak, Queue-Zugriffszeiten,
Consumer-/Producer-Thread-CPUzeit und Host-Positionierungskommandos je exklusiver
Sitzung. Die Zähler erfassen keine internen mechanischen Backhitches. Bei
überlappender Verarbeitung darf elapsed minus Gerätezeit nicht mehr als reine
Consumer-/CPUzeit interpretiert werden.

Finaler Vergleich mit künstlicher Gerätewartezeit entsprechend 112 MB/s:
synchron 48,56 MB/s, alter Prefetch 89,95 MB/s, neuer Kandidat 98,55 MB/s.
Ein voriger Vergleich ergab 70,68 / 87,42 / 98,10 MB/s. Ohne künstliche Wartezeit
erreichte der neue Kandidat in jenem Vergleich 220,54 MB/s. Es handelt sich um
kurze Softwaremodelle mit vollständiger TAR-/Datei-/Archivhashprüfung auf RAM-
Dateien, nicht um physischen Banddurchsatz oder einen garantierten Zeitgewinn.
Keine neue große Bandprüfung für diese Entwicklung. Der reale Nachweis erfolgt
beim nächsten regulären Lauf nach Reinigung; die bestehende Reinigungsaufforderung
wurde nicht umgangen oder als erledigt markiert.

266/266 Debian-Tests in 86,495 s, lokal 266 mit einem Skip in 14,750 s bestanden.
Zusätzliche Tests umfassen direkte Kurz-/Restreads, EOF/Filemark ohne Übertritt,
Fehlerweitergabe, ungültig große Records, begrenzte volle Queue, Join vor FD-Close,
RAM-Fallback/Metadatenausnahme und tatsächliche Archiv-/Rebuild-/Restorepfade am
Dateigeräteadapter. Die abgeschlossene reale LP-Katalogkopie bleibt kompatibel:
17 VERIFIED-Archive, unveränderte drei Jobdatensätze, Schema 2 und Planhash
988462bf3aaf64baf698097eda39bffe3c65fede578b4e84c2e6a1a8d7cb644a.

Installation ausschließlich im bestätigten Leerlauf, ohne Geräte-FD des Workers,
mit privatem SQLite-/Konfigurationsbackup, umask 022 für das Wheel,
Dienstkontoimport, installiertem Dateivergleich und Healthprüfung. Livekonfiguration
und alle drei LP-Jobs nachher exakt unverändert, kein neuer Job gestartet.
Web, Worker und Tunnel aktiv. Backup:
/var/backups/otam/before-overlap-083-20261022T075817.
Kandidat /var/lib/otam/acceptance-code/overlap-083-final-20261022,
Report /var/lib/otam/reports/overlap-083-20261022-r1/installation.json.
Wheel-SHA256 50bcaf3729624f6c43adf8e7aefa140f25180f7aa79cd1baed7b10050ae14f2a.
Rückweg zu 0.8.2 vorhanden. Rohdaten nur lokal ignoriert mit SHA256SUMS.
Signierter Katalogsync nach Installation:
59458c88-f1fb-4b8b-ad7b-fd84db871ee9 SUCCEEDED, Ziel UNCHANGED auf Sequenz 233.


### Dashboard-Sprungziele 0.8.4 – 22.10.2026

Die vier Statistiktafeln sind vollständige native Links: Verifiziertes Archiv →
Archive, Dateien im Katalog → Dateikatalog, Inventarisierte Medien → Bandinventar
und Vorbereitete Archive → Staging. Auf einem Katalogknoten verweist die vierte
Tafel Katalogstand auf Synchronisation. Hover und Tastaturfokus sind sichtbar;
Enter, Browser-Zurück und normale Linkfunktionen bleiben verfügbar.

JavaScript-Syntax und Diff geprüft, alle vier Ziele im Browser an isolierten
synthetischen Daten geöffnet, Enter und Tab geprüft, Screenshot lokal gesichert.
Für diese reine Oberflächenänderung wurden keine Bandtests wiederholt.
Installation im bestätigten Leerlauf mit SQLite-/Konfigurationsbackup unter
/var/backups/otam/before-dashboard-links-084-20261022T155909, Dienstkontoimport,
Wheel-Dateivergleich und erfolgreichem Healthcheck. Konfiguration und drei
LP-Jobdatensätze exakt unverändert, 17 Archive weiterhin VERIFIED. Web, Worker
und Tunnel aktiv. Katalogschema und Archivformat unverändert. Rückweg 0.8.3
vorhanden. Wheel-SHA256:
8e55891bd18c966e5243a2a1b1eaedd2e550426efdd6fc9b149d9a2850ec9b1b.
Rohbelege ausschließlich lokal ignoriert unter dashboard-links-084/ mit SHA256SUMS.


### Fotos-Master, 23.10.2026: Analyse des regulären 0.8.4-Laufs

61.034 Dateien, 525,07 GB Nutzdaten, acht Archive und acht physische
Verifikationen VERIFIED, kein Katalogfehler. Batch-Backup 7h29m02s;
Schreibdatenstrom 112,56 MB/s, Rücklesung mit vollständiger Prüfung
114,94 MB/s. Rücklese-Positionierungszähler bleiben über alle acht TARs
konstant. Keine Gerätearbeit für diese Auswertung. Details und Grenzen:
[performance-fotos-084.md](architecture/performance-fotos-084.md).
Rohdaten samt acht mbuffer-Datenlogs ausschließlich lokal ignoriert mit SHA256SUMS.


### Kombinierte Quellenübernahme und Fortschritt 0.8.5, 23.10.2026

Neue Quellenbindungen lesen Nutzdaten bei ausreichendem lokalem Staging nur
einmal: Datei-SHA während TAR-Erstellung, private gleich lange Manifestkorrektur,
danach eine unabhängige vollständige lokale TAR-/Datei-/Gesamthashprüfung.
Nur versiegelte `source_capture=single-pass-v1`-Pläne dürfen vollständig geprüfte,
unveränderte und schreibgeschützte READY-Dateien ohne zweiten lokalen Vollread
verwenden. Geschriebener Hashvergleich und vollständige physische Rücklesung
bleiben verpflichtend. Legacy-Pläne und Platzmangel-Rückfall bleiben unterstützt.
[Architektur und Grenzen](architecture/combined-source-capture.md).

Fortschritt im Jobdialog und in der Jobliste: gefundene Dateien/Größen/Pfad bei
Inventarisierung ohne erfundene Gesamtprozente; bei Hashing bzw. TAR-Erstellung
und lokaler Prüfung tatsächliche Byteanteile und Rate, bei TAR-Erstellung auch
Dateizähler und aktueller Pfad. Browserprüfung mit ausschließlich synthetischen
Vorschaudaten; keine produktiven Jobs erzeugt.

273/273 Debian-Softwaretests in 96,772 s bestanden, lokal 273 mit einem Skip
in 15,951 s. Zwei vorherige unvollständige Testpakete enthielten versehentlich
`tools/` nicht: beide Fehlerlogs bleiben erhalten; korrigiertes vollständiges
Paket bestand. Nach dem Python-Gesamtlauf wurde ausschließlich die zusätzliche
TAR-Dateizähler-/Pfaddarstellung in ui.js ergänzt, per JavaScript-Syntaxprüfung
und Browser kontrolliert und in einem getrennten UI-Releasekandidaten abgelegt.
Keine Änderung am getesteten Pythoncode oder an laufenden Testkandidaten.

Kompatibilität an isolierter Livekatalogkopie: Schema 2, 25 VERIFIED-Archive,
unveränderte vier LP-/Foto-Jobdatensätze und Planhashes. Installation im erneut
geprüften Leerlauf, keine Geräte-FDs des Workers, SQLite-/Konfigurationsbackup,
umask 022, Dienstkontoimport, exakter Wheel-Dateivergleich und Health ok.
Web/Worker/Tunnel aktiv, Konfiguration und vier Jobs danach exakt unverändert.
Backup (historischer Skriptnamenspräfix, enthält vorherige Version 0.8.4):
/var/backups/otam/before-dashboard-links-084-20261023T173910.
Kandidat /var/lib/otam/acceptance-code/combined-capture-085-release-ui-20261023,
Report /var/lib/otam/reports/combined-capture-085-release-20261023-r1/installation.json.
Wheel-SHA256 ce4fddeaf5febce6350050a9299b6498d25efbc62b880a9c552c8dc1a08ccd0d.
Rückweg 0.8.4 vorhanden. Keine Bandwrites, keine redundante physische Vollprüfung;
realer NAS-Zeitgewinn bleibt beim nächsten regulären Job zu messen. Rohdaten
ausschließlich lokal ignoriert in combined-capture-085/ mit SHA256SUMS.


### Veröffentlichung 0.8.6 mit Ersteinrichtung und Debian-Paket

Geführte erste Administratoranlage über privaten lokalen Einmal-Schlüssel,
Passwortbestätigung, transaktionale Einmaligkeit, Versuchslimit und bestehende
Konten unverändert. 279 Tests mit Debian-13-Distributionsbibliotheken in 99,257 s
bestanden; lokal 279 mit einem Skip. Paketbau und entpackter Paket-/Login-/
Neustart-Smoke-Test unter Dienstkonto an isoliertem Zustand bestanden. Eine
Probe auf dem standardmäßigen RAM-TMPDIR wurde von der Speicherpolitik korrekt
abgewiesen und anschließend auf dem qualifizierten lokalen Test-TMPDIR ausgeführt.
Die bestehende manuelle Bandserverinstallation bleibt unverändert auf 0.8.5;
kein .deb darüber installiert, keine produktiven Konten geändert, keine Bandaktion.
Details, Veröffentlichungsprüfung und Grenzen:
[public-release-086.md](public-release-086.md). Debian-Installation, Bedienung
und englischer Einstieg sind verlinkt. Rohdaten ausschließlich lokal ignoriert.

### 0.8.7 — additive Sicherung und robuste Quellenplanung (26.10.2026)

301/301 Debian-Softwaretests im getrennten Kandidatenverzeichnis bestanden;
macOS 301 Tests mit einem plattformbedingten Skip. Neue Quellenpläne unterstützen
additive Auswahl aus zugeordneten VERIFIED-Archiven und eine herstellerunabhängige
Symlink-Policy mit sichtbaren, versiegelten Ausschlüssen. NAS-Vorschauordner
`.@__thumb` werden zusätzlich vor dem Betreten ausgeschlossen. Keine Änderung
bestehender Planhashes, Bandmanifeste oder Sicherheitsjournale. Details:
[Quellen-Verknüpfungen](architecture/source-link-policy.md) und
[additive Sicherungen](architecture/additive-backups.md).

Bandserver im geprüften Leerlauf von 0.8.5 auf 0.8.7 aktualisiert. Vorher wurden
Katalog, Control, Konfiguration und die bisherige virtuelle Umgebung gesichert.
Import als Dienstkonto erfolgreich; gespeicherte Jobs/Planhashes und
Archivzustände sowie Konfiguration blieben beim Update unverändert. Keine
Bandaktionen und kein automatischer Neustart einer fehlgeschlagenen Planung.

### 27.10.2026: aktuelle Bandanzeige und automatische UI-Aktualisierung

Die Übersicht zeigt eine aktuelle Laufwerks-/Bandbeobachtung statt sämtlicher
historischer Geräteidentitäten. Alte Erkennungen und TapeAlert-Verläufe bleiben
unter aufklappbaren Diagnosedaten erhalten. Fehlende oder veraltete Erkennung
wird nicht als aktuell eingelegtes historisches Band ausgegeben. Hardwareseite
und Bandinventar aktualisieren sich alle fünf Sekunden; Pflegebereiche bleiben
aufgeklappt und Formulare werden nicht ersetzt. Eine erfolgreiche Registrierung
wird angezeigt. Das Polling liest vorhandene Statusdaten, löst keine zusätzliche
Geräteabfrage aus und ändert keine Schreibfreigaben.

Lokal bestanden 312 Softwaretests (ein Skip) sowie JavaScript-Syntaxprüfungen.
Browserprüfung mit synthetischen Geräten belegte genau eine Übersichtskarte,
automatischen Bandwechsel/Entnahme, nachgezogene Registrierung und Erhalt der
aufgeklappten Pflegebereiche. Der mit 0.8.7 kompatible UI-Bundle wurde zusätzlich
gegen das bisherige API-Format ohne `current_drive` geprüft.

Auf dem Bandserver wurden ausschließlich fünf statische Oberflächendateien auf
Basis des installierten 0.8.7-Stands gesichert und ersetzt. Keine Dienstneustarts,
Datenbank-, Konfigurations- oder Bandaktionen. Healthcheck und beide Dienste
waren danach aktiv; alle fünf per HTTP ausgelieferten Dateien entsprechen ihren
geprüften SHA-256-Werten. Version und Backend bleiben 0.8.7. Die optionale lokale
Quellübernahme des Entwicklungsbranches wurde dabei nicht mitinstalliert; die
neue Backend-Zusammenfassung ist für diese kompatible UI-Korrektur nicht nötig.

### 28.10.2026: Transferbindung überlebt einen Wechsel der Linux-Busadresse

Ein ausgeschaltetes und erneut erkanntes Laufwerk hatte dieselbe Seriennummer,
aber einen anderen sysfs-Buspfad und damit eine neue interne `drive_id`. Die
Transferauswahl verglich bisher zusätzlich diese flüchtige ID und verweigerte
korrekte LTO-4-Medien mit einer irreführenden Profilmeldung. Die dauerhafte
Transferbindung vergleicht nun Laufwerksseriennummer, unterstütztes Profil und
Mediendichte. `mounted()` fordert weiterhin eine eindeutige, aktuelle Beobachtung
der registrierten Drive-/MAM-Seriennummern; LinuxTape prüft die aktuell aufgelöste
Geräteidentität vor Geräteaktionen erneut. Staging-Fingerprint, zulässige Rate,
Puffer, Schreibschutz und alle Pending-/Tail-Prüfungen bleiben verbindlich.

Lokal bestanden 313 Tests (ein Skip); alle zehn gezielten Bindungstests bestanden
zusätzlich isoliert als Debian-Dienstkonto. Der neue Regressionstest ändert Bus-ID,
nst- und sg-Adresse bei gleicher Seriennummer und prüft die unveränderte Übernahme
von Rate/Puffer sowie die aktuelle Backend-Gerätezuordnung. Negativtests prüfen
weiterhin andere Seriennummern, Profile, Dichten und Staging-Dateisysteme.

Produktiv wurde zuerst die veraltete Transferauswahl nach striktem Vergleich der
unveränderten Werte gesichert und erneuert. Anschließend wurde ausschließlich das
geprüfte Backendmodul als gezielte 0.8.7-Korrektur unter globaler I/O-Sperre und bei
leerer Queue installiert. Modul und beide SQLite-Datenbanken wurden gesichert;
Dienstkontoimport, Dienstneustart und Healthcheck sind geprüft. Kein Archivauftrag
wurde gestartet, kein Band neu initialisiert und kein Archivplan geändert. Die
optionale Quellübernahme des Entwicklungsbranches bleibt davon unabhängig.

### 28.10.2026: 0.8.8 im bestätigten Medienwechselfenster installiert

Der aktuelle erste Medien-Kindjob war mit elf VERIFIED-TARs abgeschlossen, der
Gesamtjob WAITING_MEDIA und der backup-set-Auftrag SUCCEEDED. Queue und dauerhafte
Pending-/Resetjournale waren leer. 317 Debian-Tests bestanden im separaten Kandidaten
mit isoliertem TMPDIR. Kompatibilität des tatsächlichen gespeicherten Plans wurde
gegen private Katalog-/Controlkopien und einen Softwareadapter geprüft: nächste
Etappe ausschließlich Kind 2, unveränderter Planhash und Modus `media`, alte elf
Archive unverändert. Dies ist ein Kompatibilitätsnachweis, kein neuer Hardwaretest.

Paket 0.8.8 wurde mit SHA-256
`8d6c5c7293beaf7a9d6d5667f93f9b9a50001db3cff26a21a4197949276b51a2`
geprüft; Wheel-Inhalte entsprachen byteweise dem getesteten Kandidaten. Erneute
Leerlaufprüfung, globale I/O- und Workersperre, Sicherungen beider Datenbanken,
Konfiguration, bisherigem Paket/Metadaten und Einstiegspunkt vor Installation.
Offline-Installation ohne Abhängigkeitswechsel mit umask 022, Dienstkontoimport und
Neustart bestanden. Rückweg auf das unveränderte vorherige Paket ist gesichert.

Nach Neustart: Dienste aktiv, Healthcheck ok, frische CPU-Telemetrie, neue
Oberflächendateien ausgeliefert. Logische SHA-256-Vergleiche von Jobs, Archiven,
Dateien, Medien, Staging, Verifikationen, Restores und dauerhaften Bindungen stimmen
mit dem Stand vor dem Update überein. Band 2 bleibt PLANNED, Gesamtjob WAITING_MEDIA;
kein Bandauftrag wurde automatisch gestartet. Die optionale lokale Quellübernahme
ist jetzt ebenfalls im Paket enthalten, bleibt ausdrücklich optional und verändert
den bestehenden Plan nicht. 0.8.8 enthält keine neue mechanische Leseratenregelung.

### 29.10.2026: 0.8.9 – parallele Hashprüfung und geringere Konkurrenzlast

Nach Serverstart waren Gesamtjob und Band 2 VERIFIED; Queue, RUNNING/PLANNING-Jobs
und Pending-/Resetjournale leer. Neuer Pfad: bestehender einzelner Prefetch-Leser
hasht den gesamten TAR-Strom, Konsument prüft gleichzeitig Struktur und Dateihashes.
Alle bisherigen End-, Fehler-, Bytezahl- und Receipt-Prüfungen bleiben erforderlich;
kein geändertes Bandformat und keine zusätzliche Nutzdatenlesung. Joblisten verarbeiten
nur benötigte Planverknüpfungen statt sämtlicher historischen Inventare in Python.
Moderat bevorzugte Worker-CPU-Zuteilung über CPUWeight=200; kein Echtzeitbetrieb.

323/323 Debian-Tests bestanden, lokal 323 mit einem Skip. Kurzer RAM-only-A/B-Test
auf der tatsächlichen CPU: Median 107,20 → 135,28 MB/s; Hauptthread-CPU je identischem
64-MiB-TAR 0,594 → 0,494 s. Kein physischer oder thermischer Dauernachweis; Details
in `architecture/parallel-readback-hashing.md`. Ein erster Teststart scheiterte vor
jeder Messung an fehlenden Schreibrechten im neuen Abnahmeverzeichnis; nach gezielter
Besitzerkorrektur bestanden Vergleich und Tests. Hauptworker wurde jeweils garantiert
wieder gestartet. Historische Protokolle bleiben unverändert.

Wheel-SHA-256: `8abbdbc2e97383209c76e7909ea063f799170e052e1752cdc16ff2d1b66c5066`.
Bytevergleich des Wheels gegen den getesteten Kandidaten, Sicherung des alten Pakets,
Konfiguration und beider Datenbanken, erneute Leerlaufprüfung und Installation unter
globaler Sperre bestanden. CPU-Drop-in getrennt rücksicherbar; wirksamer Kernelwert
200. Nach Neustart beide Dienste aktiv, Health ok, Telemetrie frisch, vollständige
logische Fingerprints von Jobs, Archiven, Dateien, Medien, Staging, Verifikationen,
Restores und dauerhaften Bindungen unverändert. Signierter Katalogsync anschließend
UNCHANGED, Sequenz 1831. Kein zusätzlicher Bandjob gestartet.
