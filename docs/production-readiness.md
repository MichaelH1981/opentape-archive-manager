# Produktionsfreigabe: Stand 20.10.2026

**Status: NICHT FREIGEGEBEN.** Installiert bleibt Version 0.5.7 für Simulatorbetrieb, Katalogsuche und ausdrücklich bestätigte physische Wartung. Ein physischer Backend-Kandidat wird seit 20.10.2026 separat geprüft; die regulären CLI-/Webrouten sind weiterhin gesperrt. Ein bestandener Wartungstest darf diese Sperre nicht umgehen.

| Abnahme | Befund | Status |
| --- | --- | --- |
| Automatisierte Softwaretests | Aktueller sequenzieller/gezielter Restore-Kandidat: 156/156 Tests auf Debian bestanden, mit isoliertem lokalen Test-TMPDIR. Lokal 156 Tests mit 43 Linux-Skips. Keine Tests verändern physische Banddaten oder lösen Shutdown aus | Bestanden für den Kandidaten |
| Reale Laufwerks-/Medienerkennung | IBM ULT3580-HH4 und eindeutig identifiziertes eingelegtes Testmedium; keine aktive TapeAlert-Warnung beim letzten Scan | Bestanden, Momentaufnahme |
| Reales PAX-TAR-/Filemark-/Append-Layout | Fünf Banddateien; alle vor und nach Append zurückgelesen und gehasht | Bestanden im kleinen Testlayout |
| Unabhängige Wiederherstellung ohne OTAM-Installation | Zwei bereits vom Testband zurückgelesene Daten-/Receipt-Paare mit `tools/recover_tar.py` unter isoliertem Python 3 wiederhergestellt: je zwei Dateien, inklusive Archiv- und Ziel-Hashprüfung; temporäre Ziele entfernt | Bestanden für diese Testarchive |
| 256-GiB-Medientest | Vollständiger Schreib-/Rücklesezyklus mit SHA-256; kein echtes Bandende erreicht | Teilabnahme |
| Volles Band bis EOM und vollständig zurücklesen | Der ausdrücklich freigegebene OTAM-Wartungsauftrag erreichte das echte Bandende nach 781,41 GiB rekonstruierbaren Testdaten (`eom=true`). Vollständige Rücklesung und SHA-256-Vergleich bestanden (`0ee3c3af5b6b68327c71464bca6944f520aa5373f793395b4faf7c8b045c4b68`). Kein aktives TapeAlert-Flag; die Laufwerkszähler meldeten drei korrigierte Schreibereignisse und keine unkorrigierten Schreib-/Lesefehler. Kompression war deaktiviert. Der Kapazitätswert gilt bis zum ersten gemeldeten ENOSPC/Frühwarnbereich, nicht als erzwungenes physisches EOT | Bestanden für dieses Testmedium |
| Kontrollierter Abbruch, Neustart und Medienwechsel an echter Hardware | Position, Tail und Identität müssen vor jedem weiteren Write unabhängig geprüft werden | Offen |
| Reguläre OTAM-Pipeline auf `/dev/nst*` | Kleine Zyklen, Append und verzögerte Verifikation bestanden. Großer Zyklus mit 2 × 70 GiB am 20.10.2026 um 10:00:54 MESZ vollständig VERIFIED: physischer Archivhash, Rekonstruktion aller sechs Archive und vollständiger Restore mit identischen Ziel-Hashes. Optimierter gezielter Restore-Kandidat besteht 156 Debian-Tests; physischer Nachtest läuft separat | Großer Kernzyklus bestanden; Sicherheits-/Web-/CLI-Abnahme noch offen |
| Wiederherstellung eines regulär durch OTAM erzeugten physischen Archivs nach Verlust von Installation und Katalog | Am 20.10.2026 zwei regulär durch ArchiveService geschriebene Archive physisch exportiert und unter isoliertem Python ohne OTAM-Importe mit `tools/recover_tar.py` vollständig wiederhergestellt (2 + 1 Dateien, Archiv- und Ziel-Hashes geprüft). Zusätzlich Katalogrekonstruktion aus leerer DB und regulärer Restore bestanden. Anschließend Header und erstes Paar ausschließlich mit sg3-utils, mt-st und GNU dd gelesen und mit System-Python unabhängig wiederhergestellt; Archivhash identisch, zwei Zieldateien geprüft | Für diese regulären Testarchive bestanden |
| Eigenständiger Katalog auf Proxmox | Debian-LXC mit eigenem `otam`-Dienstkonto und Catalog-Node-Webdienst installiert. Lokaler `/healthz`, Anmeldung, geschützte Dateisuche und gesperrte Archivierungsroute geprüft. Der SSH-Tunnel blieb aktiv; der signierte Katalog-Snapshot (Sequenz 1, 98.304 Byte) wurde nach dem Bandauftrag übernommen. Bei gestopptem Bandserver-Webdienst antworteten die unabhängige Medienansicht und Dateisuche weiterhin; anschließend liefen Webdienst und Worker wieder. Nach dem Neustart des Bandservers wurde auch der Tunnel aktiv; ein expliziter Synchronisierungsauftrag `f5ee9520-0a29-4c1a-9678-e1a853c21fdf` endete `SUCCEEDED/UNCHANGED` für Sequenz 27 | Bestanden für vorhandenen Katalogstand |
| Automatische Katalogsynchronisierung bei belegtem I/O-Lock | Während des HDD-Zonentests wurden 33 automatisch geplante Synchronisierungen in wenigen Minuten als Fehler angezeigt, weil der Scheduler die I/O-Sperre nicht beachtete. Version 0.5.4 stellt fällige automatische Aufträge bis zur Freigabe der Sperre zurück; ein Wettlauf nach dem Einplanen wird als `DEFERRED` ohne Fehlertoast abgeschlossen. Linux-Regressionstest bestanden und Version 0.5.4 auf dem Bandserver installiert. Keine der fehlgeschlagenen Veröffentlichungen änderte den gültigen Peer-Katalog. Direkt nach Ende des Zonentests um 21:03:50 MESZ lief der nächste Auftrag erfolgreich; `sync_log` bestätigt `send/SUCCEEDED`, Sequenz 27 | Fehler behoben; erfolgreicher Nachlauf bestätigt |
| Admin-Shutdown aus der Weboberfläche | Version 0.5.5 bietet eine optional aktivierte, bestätigungspflichtige Schaltfläche für Admin-Konten. Die API prüft Rolle/CSRF/Node-Namen und sperrt neue Jobs; ein separater root-systemd-Helfer prüft I/O und Jobstatus erneut. 128 Softwaretests bestanden; systemd-Units statisch validiert. Echter Shutdown bewusst nicht im laufenden HDD-Test ausgelöst | Softwareabnahme bestanden; realer Shutdown später zu prüfen |
| NAS-Katalogsicherung | Noch kein gemounteter Backup-Pfad mit Zielmarker konfiguriert | Offen für verteilten Betrieb |
| Staging-HDD | Die interne SATA-HDD Seagate S1E02N8E wurde mit ext4 formatiert. Der offizielle 30-Minuten-O_DIRECT-Test bestand mit 200,88 MB/s im Mittel, 140,94 MB/s im schwächsten Fenster und 1,82 % mittlerer CPU-Beschäftigung. Fünf zusätzliche ausschließlich lesende O_DIRECT-Zonenmessungen bis 1,60 TB bestanden das 120-MB/s-FIFO-Puffermodell; Einzelwerte und Last siehe unten. SMART nach den Tests: PASSED, 0 reallozierte/schwebende/unkorrigierbare Sektoren, 0 UDMA-CRC-Fehler; die historischen Werte Runtime_Bad_Block=40 und Command_Timeout=1/1/5 blieben unverändert. Keine passenden Kernel-I/O-Fehler im Testzeitraum. Der Benutzer hat den langen SMART-Test ausdrücklich abgewählt. UUID-basierter, optionaler ext4-Mount und zusätzliche OTAM-Staging-Ressource sind eingerichtet. Nach kontrolliertem Neustart am 19.10.2026 um 21:12 MESZ wurde `/dev/sdb1` wieder automatisch mit `nosuid,nodev,noexec,noatime` eingehängt; die gespeicherte Ressourcen-Geräte-ID stimmt, Webdienst und Worker wurden aktiv | Staging-Leistung, Registrierung und Neustartprüfung bestanden |
| Aktive Staging-Anzeige und SSD-Abmeldung | Version 0.5.7 summiert registrierte lokale Staging-Dateisysteme genau einmal und zeigt Gesamt-, belegte und verfügbare Kapazität. Auf dem Bandserver ist allein `/srv/otam/staging-hdd` aktiv: 1.967.845.998.592 Byte Gesamtgröße, 1.867.807.203.328 Byte für den Dienst verfügbar zum Zeitpunkt der Prüfung. Die beiden SSD-Einträge `/var/lib/otam/staging` und `/srv/otam/staging/zusatz` wurden mit der Ressourcen-Sicherheitsprüfung abgemeldet; Dateien wurden nicht gelöscht. Der primäre Staging-Pfad und die systemd-Schreibfreigaben verweisen nur noch auf die HDD. Historische SSD-Speedtests bleiben als Testdaten erhalten, werden jedoch nicht mehr als aktive Staging-Messungen angezeigt. Webdienst, Worker und `/healthz` waren nach Installation aktiv | Bestanden für die aktuelle Konfiguration |
| Verwalteter Staging-Speedtest und Transferempfehlung | Web-Workflow mit eigener 12-GiB-Testdatei, O_DIRECT-Lesefenstern und CPU-/I/O-Wait-Messung. Version 0.5.3 bewertet kurzzeitige Einbrüche über ein kumulatives FIFO-Puffermodell statt über das schwächste Einzelsample. Mindestens 5 % Durchschnittsreserve, 15 Sekunden Reserve im Puffer und ein bis auf höchstens fünf Sekunden Zielrate aufgeholter Rückstand am Testende sind erforderlich. Der Host-Datenstrom-Grenzwert wird aus den dokumentierten Stufen des aktuell erkannten IBM-HH4/LTO-4-Profils gewählt; der Puffer bleibt editierbar. Der reale `mbuffer`-Schreibpfad ist weiterhin gesperrt | Software lokal getestet; Hardware-Abnahme offen |

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
Debian-Nachtest und ein kleiner echter Web-/CLI-Integrationszyklus stehen aus.

Scope dieses Kandidaten: ein bereits initialisiertes physisches Medium. Physische
Initialisierung und Mehrbandplanung bleiben gesperrt und benötigen eigene sichere
Workflows. Die bisherige Simulator-Mehrbandfunktion ist unverändert. Die
Produktionsabnahme ist deshalb weiterhin offen; die Installation bleibt 0.5.7.

Den laufenden Auftrag und sein Code-Verzeichnis nicht verändern oder durch
weitere intensive I/O-Tests stören. Der reguläre Worker ist bis zum Testende
angehalten und startet anschließend über OnSuccess/OnFailure automatisch.
Keine Produktionsfreigabe vor Auswertung dieses Laufs und der verbleibenden
Sicherheits-/Web-/CLI-Abnahmen.
