# Produktionsfreigabe: Stand 20.10.2026

**Status: NICHT FREIGEGEBEN.** Installiert bleibt Version 0.5.7 für Simulatorbetrieb, Katalogsuche und ausdrücklich bestätigte physische Wartung. Ein physischer Backend-Kandidat wird seit 20.10.2026 separat geprüft; die regulären CLI-/Webrouten sind weiterhin gesperrt. Ein bestandener Wartungstest darf diese Sperre nicht umgehen.

| Abnahme | Befund | Status |
| --- | --- | --- |
| Automatisierte Softwaretests | Initialisierungskandidat: 198/198 Tests auf Debian bestanden, mit isoliertem lokalen Test-TMPDIR. Der nachfolgende Medienwechselharness wird separat geprüft. Keine Tests verändern physische Banddaten oder lösen Shutdown aus | Bestanden für den Kandidaten |
| Reale Laufwerks-/Medienerkennung | IBM ULT3580-HH4 und eindeutig identifiziertes eingelegtes Testmedium; keine aktive TapeAlert-Warnung beim letzten Scan | Bestanden, Momentaufnahme |
| Reales PAX-TAR-/Filemark-/Append-Layout | Fünf Banddateien; alle vor und nach Append zurückgelesen und gehasht | Bestanden im kleinen Testlayout |
| Unabhängige Wiederherstellung ohne OTAM-Installation | Zwei bereits vom Testband zurückgelesene Daten-/Receipt-Paare mit `tools/recover_tar.py` unter isoliertem Python 3 wiederhergestellt: je zwei Dateien, inklusive Archiv- und Ziel-Hashprüfung; temporäre Ziele entfernt | Bestanden für diese Testarchive |
| 256-GiB-Medientest | Vollständiger Schreib-/Rücklesezyklus mit SHA-256; kein echtes Bandende erreicht | Teilabnahme |
| Volles Band bis EOM und vollständig zurücklesen | Der ausdrücklich freigegebene OTAM-Wartungsauftrag erreichte das echte Bandende nach 781,41 GiB rekonstruierbaren Testdaten (`eom=true`). Vollständige Rücklesung und SHA-256-Vergleich bestanden (`0ee3c3af5b6b68327c71464bca6944f520aa5373f793395b4faf7c8b045c4b68`). Kein aktives TapeAlert-Flag; die Laufwerkszähler meldeten drei korrigierte Schreibereignisse und keine unkorrigierten Schreib-/Lesefehler. Kompression war deaktiviert. Der Kapazitätswert gilt bis zum ersten gemeldeten ENOSPC/Frühwarnbereich, nicht als erzwungenes physisches EOT | Bestanden für dieses Testmedium |
| Kontrollierter Abbruch, Neustart und Medienwechsel an echter Hardware | Position, Tail und Identität müssen vor jedem weiteren Write unabhängig geprüft werden | Offen |
| Reguläre OTAM-Pipeline auf `/dev/nst*` | Kleine Zyklen, Append und verzögerte Verifikation bestanden. Großer Zyklus mit 2 × 70 GiB am 20.10.2026 um 10:00:54 MESZ vollständig VERIFIED. Optimierter gezielter Restore physisch bestanden. Gemeinsamer HTTP-/CLI-/Worker-Zyklus am 20.10.2026 um 13:15:30 MESZ mit zwei neuen TARs, physischer SHA-256-Verifikation und Restore bestanden | Kernzyklus, Web-/CLI-Einbandintegration und Headerinitialisierung der zweiten Kassette bestanden; Abbruch-/Neustart und Mehrbandabnahme offen |
| Wiederherstellung eines regulär durch OTAM erzeugten physischen Archivs nach Verlust von Installation und Katalog | Am 20.10.2026 zwei regulär durch ArchiveService geschriebene Archive physisch exportiert und unter isoliertem Python ohne OTAM-Importe mit `tools/recover_tar.py` vollständig wiederhergestellt (2 + 1 Dateien, Archiv- und Ziel-Hashes geprüft). Zusätzlich Katalogrekonstruktion aus leerer DB und regulärer Restore bestanden. Anschließend Header und erstes Paar ausschließlich mit sg3-utils, mt-st und GNU dd gelesen und mit System-Python unabhängig wiederhergestellt; Archivhash identisch, zwei Zieldateien geprüft | Für diese regulären Testarchive bestanden |
| Eigenständiger Katalog auf Proxmox | Debian-LXC mit eigenem `otam`-Dienstkonto und Catalog-Node-Webdienst installiert. Lokaler `/healthz`, Anmeldung, geschützte Dateisuche und gesperrte Archivierungsroute geprüft. Der SSH-Tunnel blieb aktiv; der signierte Katalog-Snapshot (Sequenz 1, 98.304 Byte) wurde nach dem Bandauftrag übernommen. Bei gestopptem Bandserver-Webdienst antworteten die unabhängige Medienansicht und Dateisuche weiterhin; anschließend liefen Webdienst und Worker wieder. Nach dem Neustart des Bandservers wurde auch der Tunnel aktiv; ein expliziter Synchronisierungsauftrag `f5ee9520-0a29-4c1a-9678-e1a853c21fdf` endete `SUCCEEDED/UNCHANGED` für Sequenz 27 | Bestanden für vorhandenen Katalogstand |
| Automatische Katalogsynchronisierung bei belegtem I/O-Lock | Während des HDD-Zonentests wurden 33 automatisch geplante Synchronisierungen in wenigen Minuten als Fehler angezeigt, weil der Scheduler die I/O-Sperre nicht beachtete. Version 0.5.4 stellt fällige automatische Aufträge bis zur Freigabe der Sperre zurück; ein Wettlauf nach dem Einplanen wird als `DEFERRED` ohne Fehlertoast abgeschlossen. Linux-Regressionstest bestanden und Version 0.5.4 auf dem Bandserver installiert. Keine der fehlgeschlagenen Veröffentlichungen änderte den gültigen Peer-Katalog. Direkt nach Ende des Zonentests um 21:03:50 MESZ lief der nächste Auftrag erfolgreich; `sync_log` bestätigt `send/SUCCEEDED`, Sequenz 27 | Fehler behoben; erfolgreicher Nachlauf bestätigt |
| Admin-Shutdown aus der Weboberfläche | Version 0.5.5 bietet eine optional aktivierte, bestätigungspflichtige Schaltfläche für Admin-Konten. Die API prüft Rolle/CSRF/Node-Namen und sperrt neue Jobs; ein separater root-systemd-Helfer prüft I/O und Jobstatus erneut. 128 Softwaretests bestanden; systemd-Units statisch validiert. Echter Shutdown bewusst nicht im laufenden HDD-Test ausgelöst | Softwareabnahme bestanden; realer Shutdown später zu prüfen |
| NAS-Katalogsicherung | Noch kein gemounteter Backup-Pfad mit Zielmarker konfiguriert | Offen für verteilten Betrieb |
| Staging-HDD | Die interne SATA-HDD Seagate S1E02N8E wurde mit ext4 formatiert. Der offizielle 30-Minuten-O_DIRECT-Test bestand mit 200,88 MB/s im Mittel, 140,94 MB/s im schwächsten Fenster und 1,82 % mittlerer CPU-Beschäftigung. Fünf zusätzliche ausschließlich lesende O_DIRECT-Zonenmessungen bis 1,60 TB bestanden das 120-MB/s-FIFO-Puffermodell; Einzelwerte und Last siehe unten. SMART nach den Tests: PASSED, 0 reallozierte/schwebende/unkorrigierbare Sektoren, 0 UDMA-CRC-Fehler; die historischen Werte Runtime_Bad_Block=40 und Command_Timeout=1/1/5 blieben unverändert. Keine passenden Kernel-I/O-Fehler im Testzeitraum. Der Benutzer hat den langen SMART-Test ausdrücklich abgewählt. UUID-basierter, optionaler ext4-Mount und zusätzliche OTAM-Staging-Ressource sind eingerichtet. Nach kontrolliertem Neustart am 19.10.2026 um 21:12 MESZ wurde `/dev/sdb1` wieder automatisch mit `nosuid,nodev,noexec,noatime` eingehängt; die gespeicherte Ressourcen-Geräte-ID stimmt, Webdienst und Worker wurden aktiv | Staging-Leistung, Registrierung und Neustartprüfung bestanden |
| Aktive Staging-Anzeige und SSD-Abmeldung | Version 0.5.7 summiert registrierte lokale Staging-Dateisysteme genau einmal und zeigt Gesamt-, belegte und verfügbare Kapazität. Auf dem Bandserver ist allein `/srv/otam/staging-hdd` aktiv: 1.967.845.998.592 Byte Gesamtgröße, 1.867.807.203.328 Byte für den Dienst verfügbar zum Zeitpunkt der Prüfung. Die beiden SSD-Einträge `/var/lib/otam/staging` und `/srv/otam/staging/zusatz` wurden mit der Ressourcen-Sicherheitsprüfung abgemeldet; Dateien wurden nicht gelöscht. Der primäre Staging-Pfad und die systemd-Schreibfreigaben verweisen nur noch auf die HDD. Historische SSD-Speedtests bleiben als Testdaten erhalten, werden jedoch nicht mehr als aktive Staging-Messungen angezeigt. Webdienst, Worker und `/healthz` waren nach Installation aktiv | Bestanden für die aktuelle Konfiguration |
| Verwalteter Staging-Speedtest und Transferempfehlung | Web-Workflow mit eigener 12-GiB-Testdatei, O_DIRECT-Lesefenstern und CPU-/I/O-Wait-Messung. Version 0.5.3 bewertet kurzzeitige Einbrüche über ein kumulatives FIFO-Puffermodell. HDD-Qualifikation bestanden. Reale Anwendung von 120 MB/s und 2.368 MiB im getrennten physischen Integrationskandidaten nachgewiesen; großer Test enthält Pufferfüllstand-Samples. Die installierte Version bleibt bis zur restlichen Abnahme gesperrt | Hardware-Nachweise bestanden; noch nicht produktiv aktiviert |

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
