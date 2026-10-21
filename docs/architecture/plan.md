# Entwicklungs- und Abnahmeplan

Stand 21.10.2026: **0.8.0 als Performance-/Medienwechselupdate installiert**.
Kombinierte lokale Validierung, begrenztes Read-Prefetch, aktueller Dashboardplan,
Phasenfortschritt bei Staging/Transfer und ausdrückliches Mehrband-Batchangebot
sind umgesetzt. Jobnamen/-archiv, Quellenhash-Fortschritt/ETA und Kapazitätslernen
bleiben offen; die folgenden TODOs enthalten den vollständigen geplanten Umfang.
Abnahmebelege und genaue Grenzen stehen in ../production-readiness.md.

## TODO für Version 0.8: gemessene Platznutzung und Kapazitätsprognosen

Aufgenommen am 20.10.2026 auf Nutzerwunsch; Umsetzung erst ab Version 0.8.

- [ ] Pro Archiv und Medium geplante Bytes, tatsächliche Nutz-/TAR-/Receiptbytes, Header und Filemarks sowie Laufwerks-/Medienprofil und Komprimierungsmodus dauerhaft erfassen. Verifizierte Ergebnisse von abgebrochenen oder unbestätigten Writes trennen.
- [ ] Physische Belegung und verbleibende Kapazität aus geeigneten Laufwerks-/Medienzählern erfassen, soweit belastbar verfügbar. Hostseitig übertragene Bytes sind nicht automatisch physisch belegte Bandbytes; nicht verfügbare Werte ausdrücklich als unbekannt führen. Keine zusätzlichen Banddurchläufe nur für Statistik.
- [ ] Prognose und tatsächliches Ergebnis gegenüberstellen; Schätzfehler, Format-Overhead und beobachtetes Bandende nach Profil auswerten. Merkmale wie Dateigrößenverteilung und Dateitypen aggregiert sammeln, ohne Dateiinhalte oder vollständige Quellpfade als Trainingsdaten zu benötigen. Daten bleiben zunächst lokal; kein automatischer Upload.
- [ ] Zuerst einfache empirische/statistische Kalibrierung als Vergleichsbasis prüfen. Anschließend evaluieren, ob maschinelles Lernen oder ein trainiertes Modell nachweislich bessere Vorhersagen liefert; ML ist eine Option, keine bereits festgelegte Voraussetzung.
- [ ] Prognosen mit Unsicherheit, Datenbasis und Modell-/Kalibrierungsversion anzeigen; auf unabhängigen späteren Jobs prüfen. Bei unbekannten Profilen oder zu wenigen Messungen auf native Kapazität und Formatabschätzung zurückfallen. Gelernte Prognosen dürfen Identitäts-, Schreib- und EOM-/Tail-Sperren nicht umgehen oder unbelegte Komprimierungsgewinne als garantierte Kapazität ausweisen.

Die aktuelle Version erhält hierfür weder neue Datensammlung noch ein Modell.

## TODO für Version 0.8: Job-Archiv und übersichtliche Standardansichten

Aufgenommen am 20.10.2026 auf Nutzerwunsch; Umsetzung erst ab Version 0.8.

- [ ] Abgeschlossene sowie endgültig abgebrochene Jobs ausdrücklich archivieren können, einzeln und als Mehrfachauswahl. Laufende, wartende oder noch zur Wiederaufnahme vorgesehene Jobs nicht versehentlich aus dem Arbeitsablauf entfernen; zulässige Zustände und abhängige Ein-/Mehrbandjobs prüfen.
- [ ] Archivierte Jobs aus den normalen Jobübersichten und entsprechenden Standardzählungen ausblenden. Eine getrennte, paginierte und durchsuchbare Archivansicht mit Filtern und vollständigen Jobdetails anbieten; Jobs bei Bedarf wieder in die Übersicht zurückholen.
- [ ] Archivierung als separate Darstellungseigenschaft mit Zeitpunkt und nachvollziehbarem Ereignis speichern. Ursprünglichen Jobstatus, Pläne, Berichte, Fehler, Prüfsummen und Medien-/Archiv-/Dateiverknüpfungen erhalten. Kein Löschen von Daten, Quelldateien, Staging-Ausgaben oder Sicherheitssperren; Archivierung ist keine Wiederaufnahme und keine Medienfreigabe.
- [ ] Sichtbarkeit über Web, API, CLI und Katalogsynchronisation konsistent behandeln. Migration sowie Archivieren/Zurückholen und unveränderte Nachweise testen. Automatische altersbasierte Archivierung höchstens als ausdrücklich konfigurierbare spätere Option vorsehen.

## TODO für Version 0.8: durchgängiger Fortschritt

Aufgenommen am 20.10.2026 auf Nutzerwunsch, einschließlich Schreiben und
Verifikation. Lokale Vorbereitung ist freigegeben; Installation ausdrücklich
erst nach Ende des aktuellen Produktivjobs oder am separat geprüften, vollständig
verifizierten Medienwechselpunkt (siehe Update-Abnahme unten), jeweils im Leerlauf.

- [ ] Fortschrittsbalken mit numerischen Prozenten und bearbeiteten/Gesamtbytes für Prüfsummenberechnung, TAR-Erstellung, lokale Validierung, Bandschreiben und Rückleseverifikation. Dateien und TARs zusätzlich zählen; Fortschritt auch innerhalb großer Einzeldateien melden.
- [ ] Quelleninventarisierung ohne bekannte Gesamtmenge als laufende Aktivität mit gefundenen Dateien/Bytes anzeigen. Wartephasen, Bandpositionierung, Flush/Filemark und Medienwechsel ausdrücklich benennen; keine erfundenen Prozentwerte oder Restzeiten.
- [ ] Einheitliche aktuelle Phasenanzeige in Dashboard, Jobliste, Jobdetails und Staging, einschließlich laufend aktualisierter geöffneter Jobdetails. Aggregation pro TAR, Kindjob und Medium; keinen bytegewichteten Transferbalken als gesamte Joblaufzeit ausgeben.
- [ ] Durchsatz, vergangene Zeit, Datenalter und belastbare geschätzte Restzeit je Phase anzeigen. Pause, Fehler, Neustart und Verbindungsverlust erkennbar machen. 100 % gelesene Bytes sind noch kein erfolgreicher Integritätsnachweis; VERIFIED bleibt an sämtliche Prüfungen gebunden.
- [ ] Gedrosselte persistente Fortschrittssnapshots statt eines dauerhaften Ereignisses je I/O-Block. Bestehende Zähler wiederverwenden, keine zusätzlichen Quell-/Bandlesevorgänge. Software- und UI-Abnahme vor Installation.

Technische Vorbereitung, Phasendefinitionen und Abnahmekriterien:
[Fortschrittsanzeige 0.8](progress-08.md). Noch keine Laufzeitänderung installiert.

## TODO für Version 0.8: aktueller Archivplan auf der Übersichtsseite

Aufgenommen am 20.10.2026 auf Nutzerwunsch. Der aktuelle Plan darf nicht nur
unter Staging oder in verschachtelten Jobdetails auffindbar sein.

- [ ] Auf dem Dashboard einen hervorgehobenen Bereich „Aktueller Archivplan“ anzeigen: Quelle/Auswahl, Umfang, Planstatus, aktuelle Phase und Fortschritt aus denselben Daten wie die Jobdetails. Auch vorbereitete oder auf Bestätigung wartende Pläne anzeigen, nicht nur RUNNING-Jobs.
- [ ] Quellenplan, verbindlichen Archivplan und Mehrband-Kindjobs als zusammenhängenden Ablauf darstellen. Nach Medienbindung auf den verbindlichen Plan weiterführen, statt zwei scheinbar unabhängige aktuelle Jobs zu präsentieren. Bei mehreren offenen Plänen eine eindeutige Auswahl mit Verweisen auf weitere Pläne anbieten.
- [ ] Den nächsten Handlungsschritt direkt anbieten: Zielmedien zuordnen, Archivierung starten/bestätigen, erforderliches Medium einlegen/bestätigen oder einen Fehler prüfen. Erwartete Medienbezeichnung und MAM-Seriennummer sowie die Medienfolge sichtbar machen; dieselben Rollen-, Status- und Sicherheitsprüfungen wie bisher verwenden. Ein Dashboard-Klick umgeht keine Schreibbestätigung und löst keinen automatischen Start aus.
- [ ] Planung/Hashberechnung, tatsächliche lokale TAR-Bereitstellung, Schreiben und Verifikation klar unterscheiden. „Inventar abgeschlossen“ darf nicht wie „Staging bereit“ aussehen. Details bleiben erreichbar, sind aber nicht Voraussetzung, um den nächsten Schritt zu finden.
- [ ] Live-Aktualisierung ohne Verlust von Eingaben, verständliche Mobilansicht und DE/EN-Texte prüfen. Archivierte Jobs nicht als aktuellen Plan präsentieren; nach Abschluss den Abschlusszustand nachvollziehbar anzeigen. Kein Eingriff in laufende Medienarbeit; Update nur an der unten beschriebenen geprüften Grenze.

## TODO für Version 0.8: platzabhängiges Batch-Angebot je Medium

Aufgenommen am 20.10.2026 auf Nutzerwunsch. Den laufenden Archivjob und seinen
bestätigten Verifikationsmodus unverändert lassen; Umsetzung für 0.8 vorbereiten.

- [ ] Vor der Schreibbestätigung automatisch prüfen, ob alle noch benötigten vollständigen TARs des nächsten Mediums gleichzeitig auf das gewählte lokale Staging passen. Geschätzte TARgrößen, tatsächliche belegte Dateien, bereits gültig vorhandene TARs, temporäre Artefakte, Dateisystemfreiraum und vorhandene Freiraumregeln berücksichtigen; weder Dateinutzbytes allein verwenden noch den Gesamtjob mit dem aktuellen Medium verwechseln.
- [ ] Bei ausreichendem Platz sichtbar anbieten: „Alle TARs dieses Mediums vorbereiten, danach gesammelt schreiben und vollständig verifizieren“. Bedarf und verfügbarer Platz im Bestätigungsdialog zeigen; bei Platzmangel archivweisen Ablauf anbieten und den Grund nennen. Keine automatische Umschaltung eines bereits bestätigten oder laufenden Jobs.
- [ ] Die Auswahl im geprüften Plan bzw. einem ausdrücklich erneut bestätigten, nachvollziehbaren Planwechsel festhalten: zuerst sämtliche TARs erstellen und lokal validieren, dann ohne dazwischenliegende Payload-Rücklesung nacheinander schreiben, anschließend alle neuen TARs vollständig physisch zurücklesen. Nicht nur `prepare_all` aktivieren: das allein ändert die archivweise Rücklesereihenfolge nicht. Den bestehenden `verify_mode=media`-Pfad nutzen und konsistent für Ein- und Mehrbandjobs anbieten.
- [ ] Alle TARs des Mediums bis zur erfolgreichen vollständigen Rückleseverifikation behalten; kein vorzeitiges VERIFIED oder Cleanup. Freiraum vor Ausführung sowie vor jeder weiteren TAR-Erstellung erneut prüfen. Bei zwischenzeitlichem Platzverlust vor dem Bandschreiben anhalten, statt heimlich auf einen anderen Verifikationsmodus umzuschalten oder gültige Staging-Dateien zu löschen. Bei Schreib-/Rücklesefehlern bleiben bestehende Pending-/Tail-/Wiederaufnahmesperren erhalten.
- [ ] Die Oberfläche erklärt den Nutzen: weniger Wechsel zwischen Schreiben und Rücklesen, nicht garantierter durchgängiger Bandtransport. Receipt-, Identitäts-, EOD- und lokale Sicherheitsprüfungen bleiben nötig. Batch-Staging gilt je Medium; nach dessen Verifikation weiter ausdrücklich zum nächsten Medium auffordern.
- [ ] Abnahmefälle: ausreichend/zu wenig Platz, bereits vorbereitete TARs, temporäre Restdateien, veränderter Freiraum, großes Einzel-TAR, Ein-/Mehrbandjobs und beide Verifikationsmodi. Mit instrumentiertem Softwareadapter nachweisen, dass im Batch alle neuen Payload-Writes vor dem ersten Payload-Readback stattfinden; alte Nutzdaten nicht zusätzlich lesen. Fortschritt für Batch-Vorbereitung, Schreiben und Rücklesung getrennt anzeigen.

## TODO für Version 0.8: lesbare Jobnamen zusätzlich zur UUID

Aufgenommen am 21.10.2026 auf Nutzerwunsch; Umsetzung im 0.8-Kandidaten,
keine Änderung der laufenden Installation.

- [ ] Bei der Quellenplanung einen optionalen frei vergebbaren Namen anbieten, etwa „LP Archiv – Erstarchivierung“. Ohne Eingabe einen verständlichen Vorschlag aus Quelle/Auswahl und Erstellzeit verwenden. Auch vorhandene Jobs nachträglich benennen oder umbenennen können.
- [ ] Den Namen auf Dashboard, Jobliste, Staging, in Details, Bestätigungsdialogen und Jobarchiv prominent anzeigen; UUID weiterhin kopierbar und eindeutig auffindbar halten. Suche nach Namen und UUID ermöglichen; doppelte Namen zulassen und über UUID/Erstellzeit unterscheidbar machen.
- [ ] Quellenplan und daraus erzeugten verbindlichen Archivplan nachvollziehbar verbinden. Mehrband-Kindjobs mit zugehörigem Jobnamen und Mediensegment kennzeichnen. Spätere Umbenennung konsistent darstellen, ohne historische Ereignisse umzuschreiben.
- [ ] Namen als separate Darstellungseigenschaft speichern und Änderungen nachvollziehbar protokollieren. UUID, Planhash, Medienbindungen und Bestätigungsregeln bleiben unverändert; Namen sind weder eindeutige Kennung noch Schreibfreigabe und verändern keine TAR-Manifeste oder vorhandenen Banddaten.
- [ ] Sichere Länge/Unicode-Verarbeitung, leere Eingaben, HTML-Escaping, Rollenrechte und Migration bestehender Jobs prüfen. Web, API, CLI, Export und Katalogsynchronisation konsistent unterstützen; alte Kataloge ohne Namen lesbar halten.

## TODO für Version 0.8: gepufferte Rücklesung und geprüfter Updatepunkt

Aufgenommen am 21.10.2026 auf Nutzerwunsch. Die vorhandene synchrone
Rücklese-/Hash-/TAR-Pipeline soll durch begrenztes RAM-Prefetch vom Prüfer
entkoppelt werden. Beim aktuellen Job wurden rund 54 MB/s Rücklesung mit Pausen
beobachtet, gegenüber rund 114 MB/s Schreiben. Interne mechanische
Rückpositionierungen wurden nicht gemessen; eine Ursache ist damit nicht bewiesen.

- [ ] Ein einzelner Reader liest vollständige variable Tape-Records in einen begrenzten RAM-Puffer; der Prüfer konsumiert denselben Bytefluss. Kein zweiter Gerätezugriff, keine zusätzlichen Nutzdatenreads, unveränderte vollständige Archiv-/Datei-/Manifest-/Receipt-Prüfung.
- [ ] Priorität aus der realen LP-Laufzeitdiagnose: wiederholte lokale Vollprüfungen reduzieren, Archivhash und TAR-/Dateiprüfung in einem Pass kombinieren und ersetzte Sicherheitsnachweise ausdrücklich dokumentieren/testen. Acht lokale Lesepässe je neuem TAR im bisherigen archivweisen Pfad sind belegt. Die physische Rückleseprüfung erfolgt bereits im selben Pass mit SHA. Zeitbilanz und Grenzen: [LP-Performanceanalyse 0.7.3](performance-lp-073.md). Einen bloßen Puffer oder Batchmodus nicht als Lösung der gesamten Laufzeit darstellen.
- [ ] Die erste Filemark strikt als EOF verriegeln, auch beim Vorlesen; niemals in das nächste Tape-File laufen. Vor jeder späteren Positionierung muss der Reader sicher beendet sein. Fehler, Abbruch, begrenzten Speicher, Reader-Lebenszyklus und Backpressure gezielt softwaretesten; keine verlorenen, doppelten oder umgeordneten Bytes. Bei Abbruch kein falsches VERIFIED und keine automatische Fortsetzung.
- [ ] RAM-Grenzen aus real verfügbaren Ressourcen ableiten und gleichzeitig benötigte Puffer berücksichtigen. Füllstand und getrennte Geräte-/Prüfraten messen. Ein Puffer gleicht Schwankungen aus, behebt aber keinen dauerhaft langsameren Verbraucher; Hash-/TAR-/Fortschrittskosten zusätzlich profilieren. Keine Garantie für durchgängigen Bandlauf oder weniger mechanische Bewegung ohne Nachweis.
- [ ] Ergänzung 21.10.2026: Wenn trotz Puffer häufige Stopps auftreten, Rücklese-/Prüftempo gezielt abstimmen. Geräte-Einleserate und Verifikationsrate, Pufferfüllstand/-vollzeiten, CPU pro Kern/Prozess, I/O-Wartezeiten, lokale Speicherlatenz sowie Snapshot-/SQLite-Kosten getrennt messen. Archiv-SHA, Datei-SHA, TAR-Parsing und Fortschrittsprotokollierung profilieren. Repositionierungszähler nur verwenden, wenn das Laufwerk sie belastbar liefert; akustische Beobachtung oder Hostpausen nicht als gemessene mechanische Bewegung ausgeben.
- [ ] Unterstützte interne Lesegeschwindigkeits-/Streamingregelung je Laufwerksprofil prüfen, bevor eine adaptive Rate angeboten wird. Hostseitiges Drosseln bzw. verzögertes Lesen ist keine bestätigte Änderung der internen Bandgeschwindigkeit und kann einen vollen Puffer oder Stop-and-go verschärfen. Nur geprüfte Steuerung mit stabiler Regelung, Grenzen und nachvollziehbarer Begründung anwenden; andernfalls den tatsächlichen Verbraucherengpass optimieren und die fehlende Steuerbarkeit anzeigen. Keine Verifikationsprüfung auslassen, keine neuen Positionierungsbefehle im Lesestrom und keine Anpassung des aktuell laufenden Jobs.
- [ ] Update-Abnahme für den expliziten Medienwechselpunkt: erstes Kindmedium vollständig VERIFIED, übergeordneter Job WAITING_MEDIA, zugehöriger Queueauftrag erfolgreich beendet, Worker/Geräte untätig und keine ungeklärten Live-Pending-/Resetzustände. Nur fertig implementierten und geprüften Kandidaten installieren; Datenbank-/Konfigurations-/Versionsbackup und überprüfter Rückweg erforderlich.
- [ ] Fortsetzen des bestehenden 0.7.3-Mehrbandplans mit dem 0.8-Kandidaten gegen isolierte Katalog-/Controlkopien und Softwareadapter testen: Planhashes, UUIDs, Archive, VERIFIED-Ergebnisse und zweites Kindsegment bleiben erhalten; kein Wiederholen des ersten Mediums oder impliziter Moduswechsel. Schemaänderungen müssen dazu kompatibel sein. Ein irreversibel migrierter Katalog darf nicht einfach mit einem älteren Binary geöffnet werden.
- [ ] Installation nach vollständigem ersten Medium darf nach neuer Nutzeranweisung als Alternative zum bisherigen Warten auf den Gesamtjob geprüft werden. „Geschrieben“ allein reicht nicht: laufende Rücklesung, Receiptabschluss oder Cleanup nicht unterbrechen. Wenn Kompatibilität oder sichere Grenze nicht nachgewiesen sind, bis Gesamtjobende bei 0.7.3 bleiben. Der zweite Teil startet erst nach erneuter Nutzerbestätigung. Batch-Umstellung wäre ein eigener expliziter, gehashter Planwechsel, keine stille Änderung des vorhandenen Plans.

1. **Phase 0:** leeres Repository erfassen, Alternativen bewerten, Bandformat/Schema/Risiken festhalten. Hardware-Skripte und Linux-Inventar sind lesend erfasst. Die physische Bandintegration bleibt vorläufig.
2. **Phase 1a:** package/CLI, migrationsfähige SQLite-Datenbank, persistenter Simulator mit Lock/Medien-ID/Append, Plan mit SHA-256, PAX-TAR/Manifest.
3. **Phase 1b:** Rücklesung und Receipt, strikte VERIFIED-Regel, sicherer Restore, Fehler/Abbruch/Neustart, Katalogrekonstruktion; automatisierte Tests und unabhängiges tar-Lesen.
4. **Phase 1c (Hardware-Gate):** Skripte prüfen, lesendes Linux-Inventar, explizit benanntes entbehrliches Testband und Freigabe. Erst dann Write-Adapter mit mt-st/mbuffer entwickeln und tatsächliches Close/EOD/EOM/Filemark-Verhalten validieren. Kein produktiver Einsatz davor. Erfolgreicher Simulator ersetzt diese Abnahme nicht.
5. **Phase 2:** Medienwechsel und Mehrbandplanung, erweiterte Suche/Export/Health, Kapazitätskalibrierung, große Kataloge messen. Vier Quartalsmedien nur nach dokumentierter Retention und bewusster Wiederfreigabe.
6. **Phase 3:** Web/API, separater Worker und eigenständiger Katalogdienst mit Snapshot-Replikation sind in 0.3 implementiert; systemd-/Container-Vorlagen und lokale sichere Konfiguration liegen vor. Proxmox-/NAS-Betrieb und tatsächliche iPhone-Abnahme stehen aus.
7. **Phase 4:** System-Snapshots, Gesundheitsberichte, optional Verschlüsselung.

## Version 0.5: Quellauswahl und Mehrbandjobs im Simulator

- Ein serverseitiger Dateibrowser listet reguläre Dateien und Unterverzeichnisse nur innerhalb freigegebener Quellen. Eine Auswahl kann mehrere Dateien/Ordner umfassen; gewählte Ordner werden rekursiv inventarisiert. Relative Auswahlpfade sind im gehashten, persistenten Plan enthalten. Symlinks, Spezialdateien, Pfad-Traversal und geänderte Quelldaten werden abgelehnt. Quelldaten werden nicht gelöscht.
- Mehrere ausgewählte Simulatormedien bilden einen übergeordneten Job mit unabhängigen Mediensegmenten. Vollständige TARs werden konservativ auf die Medien verteilt, ohne Datei oder TAR zu teilen. Nach jedem erfolgreich verifizierten Medium fordert `WAITING_MEDIA` die nächste ausdrückliche Bestätigung. Damit sind Quellen über der Kapazität eines einzelnen Mediums planbar.
- Wahlweise wird jedes TAR sofort zurückgelesen oder werden alle TARs eines Mediums zuerst geschrieben und dann vollständig geprüft. Im zweiten Modus bleiben alle TARs bis zur Verifikation lokal im Staging; vor dem Schreiben wird der Platz dafür geprüft. Kein Archiv erhält vorher den Status VERIFIED. Ein unerwartetes Bandende wird nicht automatisch auf ein neues Medium fortgesetzt.
- Offen für die physische Abnahme: Mountidentität über den gesamten Quelljob absichern, die Positionierungs-/Stagingkosten beider Verifikationsarten messen, Dateimengen im Millionenbereich profilieren und den geführten Wechsel auf realen LTO-Medien beweisen. Bis dahin bleiben reale Archivierungswrites gesperrt.

System-Snapshot-Workflow: ruhender Systemstand/Rescue-Boot oder atomarer Snapshot; Inventar (lsblk/blkid, Partitionstabellen, fstab/crypttab, LUKS-Metadaten, Paketliste, Bootmodus/Bootloader, Kernel/Initramfs, Mounts) mit Geheimnisprüfung; Dateisystemarchive separat; manuelle Recovery-Reihenfolge Partitionen → LUKS → Dateisysteme → Dateien → fstab/crypttab → chroot/Bootloader/Initramfs → Boot-Test in isolierter VM/Testplatte. LUKS-Header sind vertraulich. Keine automatische Partitionierung produktiver Platten. Borg-Wochenbackup bleibt unabhängig. V1-Dateiarchive sind kein vollständiger Systemstand.

Ergänzung Anforderung 20: persistentes lokales Staging, Phase INVENTORY bis STAGING_CLEANUP, konservative lokale FS-/Blockgeräteprüfung, Fehlererhalt, explizite Wiederaufnahme, Stream-Rücklesung ohne Zweit-TAR und Direct-I/O-Benchmark sind im Simulator-Kern ergänzt. Vor Phase 1c ist zusätzlich der dokumentierte lange 120-MB/s-Staging-Lesetest zu bestehen. Kurztests und bestehende /dev/null-Zuflussmessungen ersetzen diesen Nachweis nicht.
