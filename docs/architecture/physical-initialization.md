# Bestätigungspflichtige Medieninitialisierung

Stand 20.10.2026: Softwarekandidat geprüft, reale Abnahme offen.
`physical_initialization=false` ist der Standard. Aktivierung benötigt außerdem
`physical_archiving=true`, `physical_maintenance=true`, die Archive-Rolle und
den expliziten physischen Betriebsmodus. Gewöhnliche Archivierungsaufträge
initialisieren niemals Medien. Der installierte Dienst bleibt unverändert.

## Umfang und Schutz bestehender Daten

Dieser Workflow initialisiert ausschließlich Kassetten, deren MAM-Identität
lokal weder im Katalog noch in einer Medienbindung bekannt ist. Bekannte Medien
werden unabhängig von Klasse und Zustand abgewiesen, einschließlich Dauerarchiv,
Rotation, ARCHIVED, SUSPECT und RETIRED. Es gibt kein implizites Recycling und
kein automatisches Entfernen ungeklärter Pending-Marker oder Reservierungen.

Lokal unbekannt bedeutet nicht leer: Auch vorhandene fremde oder nach einem
Katalogverlust unbekannte Daten werden durch Initialisierung unbrauchbar.
Die Oberfläche warnt ausdrücklich davor. Bei verlorenem Katalog ist lesende
Registrierung/Rekonstruktion der richtige Weg. Der Kandidat erkennt nicht alle
Fremdformate und bescheinigt kein leeres Band. Die bestätigte Neuanlage ist
destruktiv, kein sicheres Löschverfahren und keine Vollbandqualifikation.

## Freigabe

`POST /api/v1/initialization/prepare` verlangt Adminrolle, Sitzung und CSRF.
Zulässige Felder: `drive_id`, `drive_serial`, `medium_serial`, `label`,
`media_class`. Die native Kapazität stammt aus dem bestätigten Profil, derzeit
IBM ULT3580-HH4 mit erkannter LTO-4-Dichte und 800.000.000.000 nativen Bytes.
Unbekannte Dichte/Profile werden ohne Annahmen abgewiesen, auch wenn eine
Kassette möglicherweise unformatiert ist. Es gibt keinen Kapazitäts-Override.

Vorbereitung liest nur aktuelle gespeicherte Erkennung und lokale Metadaten.
Der fünf Minuten gültige Grant bindet Node-ID, Drive/MAM, Profil, native Kapazität,
Bezeichnung, Klasse und Phrase `INITIALIZE <Drive-SN> <MAM-SN>`. Ein kanonischer
SHA-256-Digest erkennt versehentlich veränderte Reviewdaten; er ist kein Ersatz
für den Schutz der privaten Steuerdatenbank. Die Oberfläche zeigt die konkreten
Werte vor Eingabe der Phrase und der separaten destruktiven Bestätigung.

Adminauftrag `initialize-physical` akzeptiert nur
`{approval_id, confirmation, destructive_confirmed: true}`. Metadaten können
im Schreibauftrag nicht ausgetauscht werden. Die CLI verwendet denselben Auftrag
über `physical-command --kind initialize-physical`; Vorbereitung und Freigabe
müssen vorher erfolgt sein.

## Ausführung und Abbruch

Der Worker verbraucht die Freigabe transaktional vor Gerätezugriff. Ein anderer
vorbereiteter Grant derselben Kassette kann eine verbrauchte oder ungeklärte
Reservation nicht umgehen. Erst der Worker erkennt Hardware frisch und prüft
Identität, Schreibbereitschaft und unverändertes Profil. Unter globaler I/O- und
Laufwerkssperre wird erneut auf bekannte Medien und Pending-Marker geprüft.
Ein Katalogjob und das konkrete Bestätigungsereignis werden vor dem möglichen
Write gespeichert. UUID und MAM-Seriennummer werden anschließend katalogisiert.

LinuxTape prüft reale Identität, bestätigtes BOT und fsynct einen Pending-Marker
vor dem Writer. Der vollständige lokale PAX-Header wird geschrieben. Dateimarke,
EOD-Dateianzahl 1, Headerinhalt und physischer SHA-256-Rücklesevergleich müssen
bestehen. Der Worker vergleicht Header und Review zusätzlich. Erst danach werden
Medium und Drive-Bindung registriert. Ergebnis INITIALIZED gilt ausschließlich
für den Header: keine VERIFIED-Datenarchive und keine Vollqualifikation.

Ein Precheck-Fehler verbraucht den konkreten Grant; ein neuer Versuch benötigt
einen neuen Review. Nach möglicherweise begonnener Initialisierung bleibt eine
Reservation auch bei Fehler der nachfolgenden Katalog-/Bindungspublikation
erhalten. Prozessverlust ist kein Rollback. Explizite lesende Prüfung und
gegebenenfalls Registrierung sind erforderlich; es gibt keine automatische
Wiederaufnahme, Markerbereinigung oder neue Initialisierung.

## Abnahme

Softwaretests prüfen Admin/CSRF, Default-Gate, native Kapazität, unbekannte und
geschützte Profile, bekannte Kassetten aller Zustände, Pending-Symlink,
abgelaufene/veränderte/erneut verwendete Grants, Medienwechsel vor Ausführung,
Reservation nach tatsächlichem Ende eines Softwareprozesses, abweichenden Header
und fehlgeschlagene Katalogpublikation. Die echte LinuxTape-Zustandsmaschine wird
hinter einem Dateigerät mit dem regulären Initialisierungs-Workerpfad,
Header-Readback, anschließendem Append und Restore geprüft. Keine Geräteöffnung.

`tools/tape_initialization_acceptance.py` ist für die separate reale Abnahme
vorbereitet. Es verlangt exakte Drive-/MAM-Identität und destruktive Bestätigung,
neuen privaten Reportpfad und angehaltenen untätigen Hauptworker. Die überwachende
systemd-Unit muss den Hauptworker bei Erfolg/Fehler wieder starten. Gates gelten
nur im Speicher; die installierte Konfiguration bleibt unverändert. Livekatalog,
Live-Control, Gerätesperren und Pending-Journal werden benutzt, damit Unsicherheit
nach Testende sichtbar bleibt. Die Geräteableitung beobachtet nur und erlaubt
ausschließlich Initialisierung des bestätigten Mediums und Lesen von Position 0.
Append ist gesperrt. Der bisherige Archivpräfix muss unverändert bleiben.

Die bisherige reale Testkassette ist bereits katalogisiert und deshalb für
diesen Workflow gesperrt. Er benötigt eine zweite konkret identifizierte und
ausdrücklich für vollständigen Datenverlust freigegebene Testkassette. Vor ihrer
Freigabe erfolgen ausschließlich lesende Identifikation und Diagnose.
