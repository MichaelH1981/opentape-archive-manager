# Physischer Mehrbandkandidat

Stand 20.10.2026: softwareseitig geprüft, **nicht physisch abgenommen oder
produktiv freigegeben**. `physical_multivolume=false` ist der Standard und
benötigt bei Aktivierung zusätzlich `physical_archiving=true` und den expliziten
physischen Betriebsmodus. Initialisierung wird dadurch niemals erlaubt.

## Planung ohne eingelegte Medien

Mehrere Medien können in einem einzelnen Laufwerk nicht gleichzeitig eingelegt
sein. Der Web-/CLI-Worker verwendet daher Katalogprojektionen statt mehrmaliger
Bandscans zur Planung. `planning.catalogue_snapshot` prüft gespeicherte physische
Identität, zulässigen Medienzustand, lückenlose Positionen, ausschließlich
VERIFIED-Archive mit plausiblen Größen und SHA-256 sowie konservative Kapazität.
Die Webschicht prüft zusätzlich persistente UUID/MAM/Drive-Bindungen und bekannte
lokale Pending-Marker. Fehlende Registrierung, SUSPECT, unvollständige Folgen
oder unplausibler Verbrauch verhindern die Planung.
Verschiedene Katalog-UUIDs mit identischer MAM-Seriennummer dürfen nicht als
zwei Kassetten gezählt werden. HTTP-/Worker-Validierung und Kernplanung weisen
diese Mehrfachzuordnung unabhängig ab, bevor ein Plan gespeichert wird.

Der Plan enthält die erwartete Dateianzahl und kennzeichnet seine Basis als
Katalogschätzung. Der Kennzeichner ist Bestandteil des persistenten Planhashs.
Inventarisierung und Quellhashes werden regulär erstellt; Planung und Staging
öffnen und positionieren kein Bandgerät. Die unabhängige physische Kern-API
`ArchiveService.plan` mit übergebenem Gerät behält ihre vorhandene Vorprüfung;
der Worker verwendet ausdrücklich `plan_catalogued` beziehungsweise
`plan_set(..., catalogue_only=True)`.

## Ein bestätigtes Medium pro Schritt

Der Parent enthält geordnete Child-Jobs, je befülltem Medium einen. Ganze TARs
werden unter Beachtung der 95-Prozent-Kapazitätsgrenze verteilt. Passt ein TAR auf
keines der verbleibenden Medien, scheitert die Planung; es wird nichts geschrieben.
Ein einzelnes Medium kann weiterhin mehrere vollständige TARs enthalten.

Jeder `backup-set`-Auftrag bestätigt Parent-ID, Planhash und die Medien-UUID des
nächsten nicht verifizierten Kindes. Eine andere UUID, nicht eingelegte Kassette,
andere MAM-/Drive-Identität oder unpassende Transferwerte werden abgewiesen. Die
Hardware wird bei Ausführung frisch erkannt und im Backend unmittelbar vor
Write erneut gebunden. Der normale ArchiveService prüft Header, reale
EOD/Dateianzahl, Tail und sämtliche vorhandenen Receipts gegen den Katalog.
Zwischenzeitliche Appends machen einen früheren Offlineplan unbrauchbar.

Puffer und Hostlimit stammen aus dem zum Child-Staging gehörenden, gegen das
aktuelle Laufwerksprofil und Dateisystem geprüften Transferdatensatz. Ihre
Auswahl wird am Child protokolliert; tatsächliche Schreibereignisse und
Rückleseprüfung bleiben unverändert. Der Parent wird erst nach VERIFIED des
Kindes WAITING_MEDIA oder nach dem letzten Kind VERIFIED. Es gibt keinen
unbestätigten automatischen Medienwechsel und keine automatische Wiederaufnahme
eines fehlgeschlagenen Kindes.

Ist lediglich der letzte Parent-Abschluss verloren gegangen und sind alle
Kinder bereits VERIFIED, werden auf dem letzten Medium Identität, vollständige
Receiptkette und EOD erneut kontrolliert. Keine Nutzdaten werden dabei als neu
verifiziert bezeichnet oder allein für den Parent-Abschluss erneut gelesen.
Explizite Vollprüfung und Wiederaufbau behalten ihre vollständige Rücklesung.

## Nachweise und verbleibende Grenzen

Automatisierte Tests prüfen zwei getrennte Dateigeräte hinter der echten
LinuxTape-Zustandsmaschine: Offlineplanung und Child-Staging ohne Erkennung oder
Geräteinstanz, abgewiesenes falsches/nicht eingelegtes Medium ohne Write,
WAITING_MEDIA nach erster Verifikation, zweiter Schritt erst nach Wechsel,
physische TAR-/Receipt-Verifikation und Restore beider Gruppen, angewandtes
mbuffer-Limit und Puffer sowie verlorenen Parent-Abschluss ohne zusätzlichen
Payloadread. Ein veralteter Einzelplan nach einem anderen Append wird ohne
weiteren Writer abgewiesen. HTTP prüft auswählbare, nicht eingelegte Medien und
die standardmäßig geschlossene Mehrbandsperre.

Diese Dateigeräte emulieren SCSI-Positionen; sie beweisen keinen realen
Medienwechsel, keine reale Laufwerksreaktion bei Entnahme und keinen realen
Schreibabbruch. Für die physische Abnahme müssen zwei konkrete Testkassetten
ausdrücklich freigegeben sein. Gegenwärtig ist nur die bisherige Testkassette
freigegeben. Keines der anderen vorhandenen Medien darf dafür verwendet werden.
Der echte Tail-/Neustarttest ist anschließend gezielt klein durchzuführen.
Die unabhängige [Initialisierungsabnahme](physical-initialization.md) bleibt
vor Produktivaktivierung offen. Recycling bereits bekannter Kassetten bleibt ein
separater gesperrter späterer Workflow. Restore-Aufträge werden weiterhin pro
ausgewählter Medien-/Archivgruppe bestätigt; ein übergreifender automatischer
Restore-Wechsel ist kein Teil dieses Kandidaten.
