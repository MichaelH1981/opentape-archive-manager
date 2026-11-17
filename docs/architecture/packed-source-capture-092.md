# Direkte Quellenübernahme in TARs — 0.9.2

## Ablauf und Platzbedarf

Neue `stage-source`-Aufträge und neue rollierende Generationen lesen die
Quelldaten direkt in eigene lokale, unkomprimierte PAX-TARs. SHA-256 entsteht
während dieses einzigen Inhaltsreads der Originalquelle. Ein unabhängiger
lokaler Prüfdurchgang kontrolliert danach jedes TAR, jede enthaltene Datei und
den vollständigen TAR-Hash. Es entsteht keine zusätzliche Einzeldatei-Rohkopie.
Der Platztest verlangt die konservative TAR-Schätzung, nicht mehr Nutzdaten
plus TAR-Schätzung. Kleine Metadaten, Rundungen und alte Test-/Fehlerartefakte
benötigen weiterhin Platz. Dies ist keine Platzreservierung gegen andere Prozesse.

Zielmedien müssen dafür noch nicht ausgewählt oder eingelegt sein. Der lokale
Zwischenstand hat `capture_only: true` und eine Null-UUID als ungebundene
Medienkennung. Es werden keine Katalogmedien oder Bandarchive daraus erzeugt;
kein Bandadapter erhält diese Zwischenstände. Ein gewöhnlicher Metadatenplan
ohne optionale Übernahme bleibt weiterhin möglich.

## Späte Bindung ohne zweite Nutzdatenkopie

Das erste TAR-Mitglied `OTAM/manifest.json` reserviert zusätzlich 8192 Byte
JSON-Whitespace. Bei der späteren Bindung stehen Dateigruppen und Hashes fest.
Nur dieser reservierte Bereich des privaten lokalen TARs wird mit endgültiger
Medien-/Archiv-ID und gegebenenfalls dem begrenzten Recoverydescriptor ergänzt.
Nutzdatenoffsets und Dateigröße bleiben unverändert. Eine neue Gruppierung oder
zu große Metadaten führen zum Abbruch; es gibt keinen stillen NAS-Rückfall.

Ein exklusiv angelegter, fsyncter Bindungsintent steht vor Verschieben/Ändern.
Der Payload-Inode wechselt auf demselben Dateisystem ins eigene endgültige
Stagingverzeichnis. Nach dem Manifestabschluss prüft ein weiterer vollständiger
lokaler Pass die endgültigen TAR-Strukturen und alle gespeicherten Dateihashes
und berechnet den endgültigen TAR-Hash. Erst dann wird READY exklusiv publiziert;
der verbindliche Archivplan entsteht erst nach erfolgreicher Vorbereitung aller
zugehörigen TARs. Es werden niemals Medienkennungen oder Hashes eines bereits
publizierten Plans geändert. Die Bandformate und unabhängige PAX-Recovery
bleiben unverändert; zusätzliches JSON-Whitespace ist standardkonform.

Der Bindungsauftrag benötigt nur kleinen freien Metadatenplatz (1 MiB), nicht
nochmals freien Platz für sämtliche Payloads. Die Abnahme prüft, dass vor und
nach der Bindung dieselben Payload-Inodes existieren. Ein neues TAR kann dabei
nicht allein durch eine alte Quellenhashliste als geprüft gelten.

## Fehler, Aufbewahrung und Kompatibilität

Quellöffnungen und Fingerprints vor/nach Lesen, Ausschlüsse, lokale
Stagingzulassung, Dateihashes und die vollständige physische Rücklesung bleiben
verbindlich. Ein Abbruch beim Binden erhält Intent und Partial. Es gibt keine
automatische Wiederholung, keine automatische Intentbereinigung und keine
Neuübernahme aus der inzwischen möglicherweise geänderten Quelle. Solche
Zwischenstände benötigen eine ausdrückliche Diagnose; sie werden nicht als
fortsetzbarer Plan oder VERIFIED präsentiert.

Bei rollierenden Generationen liegt die vollständige lokale Quellenaufnahme
nach der Bindung in den endgültigen TARs. Diese bleiben auch nach einzelnen
verifizierten Archiven erhalten, bis die ganze Generation verfügbar VERIFIED
ist. Der reguläre Worker bereinigt dann automatisch nach erfolgreichem Abschluss;
ein manueller Adminauftrag mit Vorschau kann eine verschobene Bereinigung nachholen. Die kleinen
Owner-/Bindungsjournale bleiben als Nachweis erhalten. Bei normalen Archivjobs
gilt weiterhin die reguläre Bereinigung nach VERIFIED. Staging ist in beiden
Fällen keine unabhängige Sicherung.

Alte Rohkopien (`otam-source-capture-v1`), bestehende Archivpläne, Medienbindungen,
Planhashes und Verifikationsmodi bleiben unverändert les-/ausführbar. Es ist keine
Datenbankschemaänderung nötig. Bestehende Jobs werden nicht automatisch auf den
neuen Übernahmeweg umgestellt. Vor einem späteren Rollback dürfen keine neuen
gepackten Quellenpläne aktiv sein: 0.9.1.1 versteht dieses Captureformat nicht.
Ein Rückweg muss mit den gesicherten Datenbanken und dem gesicherten Programm
vor dem Update erfolgen; kein blindes Downgrade über neue 0.9.2-Aufträge.

Diese Änderung ermöglicht keine beliebig großen Quellen bei kleinerem Staging:
die vollständige TAR-Menge muss weiterhin hineinpassen. Ein begrenztes rollendes
Staging mit abschnittsweisem Lesen/Schreiben wäre eine separate Erweiterung.

## Vorbereitung der Veröffentlichung

0.9.2 wird getrennt gebaut und softwaregeprüft. Kein Eingriff in einen laufenden
Archivauftrag, keine zusätzlichen Hardwaretests auf produktiven Bändern und
keine Installation vor dessen Abschluss. Simulator-/Dateigerätetests ersetzen
keinen behaupteten physischen Durchsatznachweis.
