# Quellen, Staging und physische Bandwartung

## Ressourcen und Verzeichnisauswahl

Quellen und Staging-Verzeichnisse werden über Einstellungen bzw. Planung/Staging hinzugefügt. Der Dialog zeigt vorhandene Verzeichnisse innerhalb der administrativ festgelegten `directory_roots` sowie bisheriger Quellen und Standard-Staging. Keine automatische Freigabe des gesamten Servers, kein Mounten, Formatieren oder Anlegen von Benutzerverzeichnissen. Interne Katalog-/Queue-/Medien-/Restore-Verzeichnisse und Symlink-Ausbrüche werden ausgeschlossen. Quelldateien werden weder gelöscht noch durch die Registrierung verändert.

Neue Ressourcen werden in der privaten Steuerdatenbank gespeichert. Quellen und Staging dürfen sich nicht überschneiden, auch nicht mit Snapshot-Zielen. Staging muss auf einem bestätigten lokalen, schreibbaren Dateisystem liegen; Speicherinformationen erscheinen in der Oberfläche. Ressourcen werden unveränderlich angelegt, um alte Pläne nicht nachträglich umzuleiten. Abmelden entfernt die Auswahl, keine Dateien. Gebundene Jobs bzw. unverifizierte Archive verhindern Abmeldung. Bestehende Konfigurationen bleiben nutzbar.

Ein Archivplan wählt `source_id` und `staging_id`. Die Staging-Zuordnung wird je Job persistent gespeichert und vor Stage/Backup erneut aufgelöst; der Kern erzwingt zusätzlich den ursprünglichen Staging-Pfad bereits vorbereiteter Archive. Quell-Unterverzeichnisse lassen sich im Dialog auswählen und als eigene Quelle registrieren. Ein anderer Mount oder fehlende Rechte werden als Fehler gemeldet. systemd-Schreibpfade müssen für zusätzliche Staging-Mounts administrativ freigegeben werden. Die Oberfläche erweitert keine Betriebssystemrechte.

## Betriebsarten

Standard ist weiterhin **Simulator**. Unter Hardware kann ohne Neustart auf **physischen Wartungsbetrieb** gewechselt werden, sobald der Administrator `physical_maintenance=true` und passende Workerrechte eingerichtet hat. Der Moduswechsel schreibt nichts. Bei wartenden/laufenden Aufträgen ist ein Wechsel gesperrt; im physischen Modus werden Simulator-Archivierungsaufträge abgelehnt. Synchronisation bleibt verfügbar.

**Reguläre Archivierung auf echten Bändern ist weiterhin nicht freigegeben.** Die Positionierungs-, Filemark-, EOM- und Append-Abnahme des Archivformats kann ohne ein ausdrücklich freigegebenes Testband nicht ersetzt werden. `LinuxTape` bleibt gesperrt; die neue Klasse `LinuxMaintenance` führt ausschließlich die getrennten destruktiven Wartungsabläufe aus. Diese Einschränkung ist in der UI sichtbar. Kein Umschalter darf einen Simulatorkatalog als erfolgreiches physisches Archiv ausgeben.

## Erkennung und Identitätsbindung

Der Worker erkennt etwa alle zehn Sekunden Linux-SCSI-Tape-Non-Rewinding-Geräte aus sysfs. Ein manueller Erkennungsauftrag ist ebenfalls möglich. Es werden weder Gerätepfade aus Browseranfragen noch feste Laufwerksnummern vorausgesetzt. Eine eindeutige Laufwerksseriennummer (VPD 0x80), `MTIOCGET`-Status und die MAM-Medienseriennummer (READ ATTRIBUTE 0x0401, read-only über sg3-utils) sind Voraussetzung für Schreibfreigaben. Ohne diese Daten bleibt das Gerät sichtbar, aber gesperrt. Bei fehlendem oder schreibgeschütztem Medium gibt es keine Freigabe.

Der Browser bereitet eine konkrete Aktion vor und bestätigt Laufwerks- und Medienseriennummer durch exakte Texteingabe sowie eine gesonderte Destruktiv-Checkbox. Diese Freigabe gilt fünf Minuten und genau einmal. Vor Hardwarezugriff wird sie transaktional verbraucht. Unter exklusivem OTAM-Laufwerkslock werden Identität und Schreibschutz erneut geprüft, auch vor dem Rücklesen. Ein ausgetauschtes Laufwerk/Medium, abgelaufene Freigabe oder Neustart nach begonnenem Job führt nie zu blindem Fortsetzen. Fremde Programme, die außerhalb OTAM auf das Laufwerk zugreifen, sind administrativ auszuschließen; der Linux-Treiber weist gleichzeitig offene Bandgeräte üblicherweise mit EBUSY zurück.

Web und Worker bleiben unprivilegiert. Die Web-Unit behält `PrivateDevices=true`. Nur der Worker erhält optionalen Zugriff auf Band-Character-Devices und passende Tape-SCSI-Generic-Geräte durch dedizierte udev-Gruppe und systemd-DevicePolicy. Es gibt keine Web-Sudo-Schnittstelle und keine pauschale Mitgliedschaft in der Disk-Gruppe.

## Vollständiger destruktiver Qualifikationstest

1. Persistenter zufälliger 256-Bit-Seed und Formatversion werden vor dem Schreiben protokolliert.
2. Aus SHAKE-256 entsteht ein rekonstruierbares 64-MiB-Testmuster im RAM. 512-KiB-Bandblöcke enthalten eine fortlaufende Blocknummer; der erste Block enthält Magic, Seed und Formatparameter. Das Muster ist kein OTAM-Archiv und keine Nutzdatensicherung.
3. Das freigegebene Testband wird zurückgespult, auf variable Blocklänge gestellt und Hardwarekompression deaktiviert. Diese Einstellungen werden protokolliert und nicht stillschweigend zurückgesetzt.
4. Es wird bis zum ersten regulären `ENOSPC` geschrieben. Dies ist die **nutzbare Kapazität bis zur Early-Warning-Grenze**, nicht gewaltsames Schreiben bis zum physikalischen Hartende. Kein Umgehen der Warnzone. Ein zusätzliches 20-TB-Sicherheitslimit verhindert unbegrenzte Ausführung ohne Bandende; dessen Erreichen ergibt keinen bestandenen Volltest.
5. Nur vollständig bestätigte Blöcke zählen. Kurzschreiben, EIO und Fehler beim Schließen/Filemark sind Fehler. Anschließend vollständiges Zurücklesen ohne zweite Archivdatei: jeder Block wird rekonstruiert, Position, Datenmenge und SHA-256 werden verglichen. Nur vollständige Gleichheit ergibt VERIFIED. Zusätzliche, fehlende oder beschädigte Blöcke ergeben FAILED/INCOMPLETE.
6. Fortschritt, Durchsatz, Seed, Hashes und verfügbare TapeAlert-/Fehlerlogseiten werden dauerhaft gespeichert. Fehlende Gesundheitsdaten bleiben als unbekannt erkennbar und sind keine Lebensdauerprognose.

Der Wartungstest verwendet bewusst direkte, zählbare Block-Schreibaufrufe des Linux-Treibers statt eines unbestätigten mbuffer-Vorlaufs: die Zahl tatsächlich akzeptierter Testblöcke muss bei ENOSPC nachvollziehbar bleiben. Das ist eine Ausnahme für destruktive Diagnose; reguläre Archivierungsjobs behalten vollständig lokales TAR-Staging und die vorgesehene mbuffer-Pipeline. Das Testmuster wird einmal im RAM erzeugt, nicht vom NAS gestreamt. Die erreichbare Rate kann durch CPU/Hashing und das Laufwerk begrenzt sein und ist kein zugesicherter Produktivdurchsatz.

Grundlagen: [Linux SCSI Tape Driver](https://www.kernel.org/doc/html/latest/scsi/st.html), [Linux st(4)](https://man7.org/linux/man-pages/man4/st.4.html), [sg3-utils-Attributdefinitionen](https://sources.debian.org/src/sg3-utils/1.42-2/src/sg_read_attr.c/). Die tatsächliche Geräteverträglichkeit des neuen Volltests muss mit einem ausdrücklich freigegebenen Testmedium geprüft werden.

## Löschen

**Kurzlöschen** führt `mt erase 0`, **Langlöschen** `mt erase 1` ab Bandanfang aus. Kurzlöschen ist eine logische Wiederfreigabe; Langlöschen nutzt das laufwerksseitige lange Löschkommando und kann Stunden dauern. Das Ergebnis lautet ERASE_COMMAND_COMPLETED, niemals VERIFIED oder „sicher vernichtet“. Es wird keine zertifizierte Datenträgerbereinigung oder forensische Unwiederherstellbarkeit behauptet. Bei unbekannter Identität oder Schreibschutz ist beides gesperrt. Kein automatisches Löschen im Hintergrund.

## Abnahmegrenze

Automatisierte Tests verwenden ausschließlich einen speicherbasierten Band-Doppelgänger und synthetische lokale Dateien. Sie testen EOM, vollständige Rücklesung, Blockvertauschung/-beschädigung, Kurzschreiben, I/O-/Filemark-Fehler, Sicherheitslimit, beide Löschvarianten, einmalige/abgelaufene Freigaben, Quellen-/Staginggrenzen, Jobbindung und Rollen/CSRF. Kein Test darf physische Bandgeräte öffnen. Am 18.10.2026 war das IBM-Laufwerk auf dem Bandserver nicht in sysfs vorhanden; reale Hardwareabnahme und tatsächlicher qualifizierender Volltest sind weiterhin offen.

## Zeitlich begrenzter Dauertest

`qualify-sample` überschreibt das ausdrücklich freigegebene Medium ab BOT mit
rekonstruierbaren Daten. Es schreibt höchstens 256 GiB oder 50 Minuten (Prüfung
zwischen vollständigen Records), schließt die Banddatei mit Dateimarke und liest
alle geschriebenen Records vollständig zurück. Ein früheres echtes ENOSPC wird
protokolliert; Bandende wird niemals künstlich simuliert. Nur identische Records,
Datenmenge und SHA-256 ergeben `SAMPLE_VERIFIED`. Dies ist keine Vollqualifikation
des Mediums. Die Rücklesezeit und blockierende Hardwarekommandos haben kein hartes
Zeitlimit; bei langsamen oder fehlerhaften Geräten kann der Gesamtlauf länger dauern.
Freigabe, Identitätskontrolle, Sperren und Wiederanlaufsperre entsprechen dem Volltest.

Laufwerksseriennummern werden aus VPD 0x80 gelesen; fehlt die sysfs-Datei, wird
dieselbe Seite lesend mit `sg_inq` abgefragt. `sg_logs --raw --raw` liefert die
vollständige Logseite einschließlich des vom Parser benötigten Headers. Ein
einzelnes `--raw` liefert bei sg3_utils nur Parameter und ist dafür ungeeignet.

Bei Linux sg benötigt READ ATTRIBUTE (MAM) einen mit Schreibberechtigung geöffneten
sg-Dateideskriptor; `sg_read_attr --readonly` scheitert für den Dienstbenutzer mit
EPERM. OTAM verwendet daher `sg_read_attr --raw --first=0x401` ohne `--readonly`.
Das ausgeführte SCSI-Kommando bleibt READ ATTRIBUTE; WRITE ATTRIBUTE wird nicht
verwendet. Die Tape-only-Gerätegruppe reicht aus, zusätzliche Root-Capabilities
sind nicht erforderlich. Auf dem IBM-Laufwerk mit Debian 13 überprüft.
