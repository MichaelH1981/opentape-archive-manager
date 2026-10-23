# Kombinierte Quellenübernahme, 0.8.5

Neue Web-/Queue-Quellenpläne behalten die schnelle Metadatenplanung vor der
Medienwahl. Nach ausreichender Medienkapazität wird lokales Staging geprüft.
Passen alle geplanten TARs hinein, verbindet die Bindung Datei-Hashing und
TAR-Erstellung in einem Inhaltsdurchgang. Bei Platzmangel bleibt der bisherige
Hash-/Stage-Pfad verfügbar; `combined_capture_policy` nennt Auswahl, freien
Platz und Bedarf. Es gibt keine zusätzliche vollständige Rohkopie.

## Fertigstellung und Freigabe

Medienzuordnung und vollständige TAR-Gruppierung stehen vor dem Inhaltsread
fest. Die Metadatenauswahl wird erneut geprüft; jeder geöffnete Quell-FD muss
zum ursprünglichen Fingerprint (Gerät/Inode/Größe/mtime/ctime) passen und nach
dem Kopieren unverändert sein. Dateien werden unter `data/` in einen eigenen
privaten `.partial`-TAR geschrieben; SHA-256 entsteht während dieses Lesens.
Symlink-/Sonderdateisperren und genaue Größenkontrollen bleiben erhalten.

Das bestehende TAR-Format beginnt mit dem vollständigen Manifest. Während
privater Erstellung enthalten dessen Hashfelder feste 64-stellige Platzhalter.
Nach dem letzten Payload wird ausschließlich dieser gleich lange JSON-Bereich
ab Offset 512 durch das endgültige Manifest ersetzt und fsynct. Die TAR-Header-
Größe und Payloadpositionen bleiben gleich. Dieses Zwischenartefakt wird nicht
als gültiger Plan oder READY publiziert. Nach Finalisierung prüft ein kompletter
unabhängiger lokaler Pass TAR-Struktur, sämtliche Dateihashes und den gesamten
finalen TAR-Hash. Der TAR-Gesamthash entsteht bei dieser Prüfung, nicht vor dem
abschließenden Manifestpatch. Erst danach erfolgt schreibgeschützte, exklusive
READY-Publikation und Speicherung des endgültigen versiegelten Plans.

Der Plan markiert diesen Weg mit `source_capture=single-pass-v1`. Bei späterem
Backup darf ein solcher Plan seine vollständig geprüften READY-TARs anhand des
persistierten Hashes und unveränderten schreibgeschützten Fingerprints verwenden.
Damit entfällt die zweite vollständige lokale Passage auch bei einem späteren
Workerauftrag. Fehlende/unterbrochene READY-Zustände oder Identitätsänderungen
werden nicht still akzeptiert. Explizite Revalidierung bleibt möglich.
Legacy-Pläne prüfen persistierte READY-Dateien bei neuem Zugriff weiterhin voll.
Innerhalb eines Store-Aufrufs verhindert ein flüchtiger Prüfnachweis die direkt
doppelte vollständige Prüfung auch im bisherigen Inline-Backup-Pfad.

Die Abwägung ist ausdrücklich: Zwischen unabhängiger lokaler Prüfung und Write
wird die unveränderte Dateidentität kontrolliert, nicht nochmals jeder Byte
vorab gelesen. Unsichtbare spätere Inhaltsfehler werden weiterhin durch den
Vergleich des tatsächlich geschriebenen TAR-Hashes und die vollständige
physische Rücklesung erkannt; sie können niemals VERIFIED werden. Diese
Kontrollen und Pending-/Tail-/Medienprüfungen wurden nicht abgeschwächt.

Mehrbandpläne bereiten pro Kind die bereits zugeordneten TARs vor. Ein neuer
verbindlicher Parent wird erst nach Erfolg publiziert. Fehler lassen eigene
Partial-/READY-Artefakte und fehlgeschlagene Planungsjobs zur Diagnose erhalten;
keine automatische Löschung, keine automatische Wiederaufnahme eines
unveröffentlichten Plans. Originalquelle und Bandinhalte bleiben bei dieser
Planungs-/Stagingphase unverändert. Es entsteht kein atomarer NAS-Snapshot;
Änderungen während eines einzelnen Reads werden erkannt, eine Quelle kann sich
nach erfolgreichem Erfassen eines früheren Files trotzdem weiter ändern.

## Fortschritt

`planning_progress` zeigt beim Inventarisieren gefundene Dateien, erfasste Größen,
aktuellen Pfad und Zeit. Solange die Gesamtmenge unbekannt ist, bleibt der Balken
unbestimmt. Bei bekanntem Hashumfang werden tatsächliche Byteanteile und
Durchsatz angezeigt. Während der kombinierten Übernahme verweist der Quellenplan
per `planning_child` auf den aktiven Archivjob; dessen persistierte Stagingzeilen
liefern TAR-bezogenen Fortschritt. `staging_progress` enthält zusätzlich aktuelle
Datei, Dateizähler und mittlere Nutzdatenrate. Lokale Prüfungen melden
`validation_progress`; ihre Rate wird nicht mit einer alten Kopierrate verwechselt.
Die Anzeigen gelten für die jeweilige Phase bzw. das aktuelle TAR, nicht als
Prozentwert des gesamten Archivierungsaufwands. Noch keine prognostizierte ETA.
Die detaillierte aktuelle Datei während der TAR-Erstellung ist auch im Protokoll
vorhanden. Inventar-/Hashpfade erscheinen in der laufenden Planungsanzeige.

## Abnahme

Neue Tests zählen tatsächlich gelesene Quellbytes (genau einmal Nutzdaten),
prüfen finalisierte Manifeste und schreibgeschützte TARs, Backup/Restore ohne
Originalquelle, Ablehnung von Änderungen während Kopie, Platzmangel vor
Publikation, fehlschlagende lokale Prüfung mit erhaltenem Partial und fehlendem
finalen Plan sowie Quellen-/Staging-Trennung. Bestehende negative Batchtests
prüfen weiterhin, dass alle lokalen Prüfungen vor dem ersten Write abgeschlossen
sein müssen und ein später beschädigtes TAR nicht geschrieben wird.
Keine neuen großen Hardwaretests, kein behaupteter realer NAS-Zeitgewinn.
Bestehende Pläne behalten Hashes, Medienbindungen und Verifikationsmodus.
