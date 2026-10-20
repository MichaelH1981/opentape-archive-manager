# Physischer Backend-Kandidat

Stand 20.10.2026: Entwicklung und Abnahme; keine Produktionsfreigabe.

`LinuxTape` implementiert dieselbe Schnittstelle wie der Simulator. Der reguläre
`ArchiveService` erzeugt weiterhin Plan, Staging-TAR, Rückleseprüfung, Receipt und
Katalogeintrag. Das Hardware-Abnahmewerkzeug `tools/tape_pipeline_acceptance.py`
benutzt diesen Dienst unverändert und akzeptiert ausschließlich selbst erzeugte
Testdateien. Es ersetzt weder den regulären Webworkflow noch die abschließende
Freigabe.

## Identität und Position

Das Backend erhält ein vollständig erkanntes Laufwerk einschließlich Laufwerks-
und MAM-Medienseriennummer. Es benutzt die gemeinsame Laufwerkssperre der Wartung.
Die alte Übergabe eines bloßen `/dev/nst0`-Pfades bleibt gesperrt. Schreibgeschützte
Medien dürfen gelesen werden; unmittelbar vor dem Öffnen zum Schreiben wird die
Identität zusätzlich mit geforderter Schreibbereitschaft geprüft.

Nur `/dev/nst*` und bestätigte Linux-st-Optionen werden akzeptiert. Zwei-Filemark-,
SYSV-, Fast-EOM- und asynchrone EOF/Nowait-Modi sind nicht zugelassen. Die im
Hardwaretest beobachteten Optionen sind `0x107`. Der Blockmodus wird explizit auf
variable Blöcke gesetzt. Ein vorhandener Inhalt wird ausschließlich gelesen;
Initialisierung ist eine separate, ausdrücklich mit der MAM-Seriennummer zu
bestätigende destruktive Aktion.

Lesepositionen entstehen aus Rewind und FSF mit anschließender Prüfung auf
Banddateinummer und Block 0. Die Dateizahl wird am tatsächlichen EOD bestätigt;
negative/unklare Zähler und unbekannte EOD-Zustände sperren den Vorgang. Append
prüft erneut EOD, Dateizahl, Schreibschutz und Medienidentität. Es schreibt keine
zusätzliche Filemark: der bestätigte Close des st-Schreibdeskriptors muss genau
eine neue Banddatei ergeben.

## Nicht rückrollbare Schreibversuche

Vor jedem Öffnen zum Schreiben entsteht ein mit fsync gesicherter Marker unter
`state/physical-pending/`, gebunden an die gehashte MAM-Seriennummer. Er wird erst
nach erfolgreichem Close und bestätigter neuer Filemark entfernt. Fehler und
Prozessabbrüche lassen ihn bestehen. Ein späterer Aufruf darf ihn nicht einfach
entfernen oder den Schreibvorgang wiederholen.

Nach einem vollständigen Daten-TAR ist die Anzahl der Banddateien gerade: der
Receipt fehlt noch. Nur dasselbe laufende Backend darf dann den passenden Receipt
anhängen. Seine Medien-ID, Position, Bytezahl und SHA-256 müssen dem gerade
geschriebenen Datenstrom entsprechen. Nach Neustart ist diese Ausnahme verloren;
ein unvollständiger Tail sperrt weiteres Append. Frühere vollständige Paare bleiben
für unabhängige Rücklesung und Wiederherstellung zugänglich.

Ein kurzer Schreibvorgang wird als möglicher EOM-Fehler behandelt. Der Rest wird
nicht erneut geschrieben. Der mbuffer-Prozess wird bei einem Ausgabefehler
beendet, damit der Fehlerpfad nicht auf einem gefüllten Pipe-Puffer hängen bleibt.
Schlägt anschließend auch die Positions-/Kapazitätsabfrage fehl, protokolliert der
Dienst weiterhin den ursprünglichen Fehler, kennzeichnet das Medium als SUSPECT
und reserviert konservativ dessen gesamte Kapazität.

## Staging und Rücklesung

Daten-TARs und Receipts liegen vollständig lokal vor. Der Dienst prüft die
Staging-Artefakte vor dem Schreiben vollständig; der Adapter verlangt zusätzlich
ein lokales Dateisystem, reguläre Dateien ohne Schreibbits, unveränderte
Dateimetadaten und eine passende Bytezahl. mbuffer liest über einen bereits sicher
geöffneten Deskriptor. Es gibt kein Netzwerk-zu-Band-Streaming.

Die Rücklesung großer Datenarchive erfolgt direkt als Stream. Nur kleine Header-
und Receipt-TARs werden begrenzt lokal materialisiert. Der Dienst vergleicht
Archivhash, Bytezahl, Manifest und Nutzdatei-Hashes. Die gesondert bestätigte
Initialisierung prüft auch den Header physisch zurück. VERIFIED und Staging-Cleanup
bleiben an die vollständige erfolgreiche Rücklesung gebunden.

`TapeRecordReader` liest physisch stets mit einem ausreichend großen Puffer,
bedient daraus auch kleine Byte-Anforderungen (etwa den TAR-Standardpuffer von
10 KiB) und merkt sich die erste gelesene Filemark. Weitere Leseaufrufe auf
derselben offenen Banddatei geben dann ausschließlich EOF zurück. Ein gewöhnlicher
BufferedReader direkt auf dem st-Deskriptor würde diese Garantie nicht liefern:
ein Read hinter der ersten Filemark kann beim st-Treiber zur nächsten Banddatei
führen. Die Record-Schicht verhindert sowohl ENOMEM bei zu kleinen Read-Puffern
als auch versehentliches Zusammenlesen benachbarter TARs.

## Transfersteuerung im Kandidaten

Der Adapter akzeptiert eine explizite Host-Datenstromrate nur aus dem bestätigten
Profil des erkannten Laufwerks und Mediums. Sie wird als Byte/s-Wert an mbuffer
`-R` übergeben; das setzt kein SCSI-Kommando für eine feste mechanische
Bandgeschwindigkeit ab. `-P 90` sorgt für Vorfüllung; kleine vollständig gelesene
Archive dürfen nach EOF auch unterhalb der nominellen Puffergröße ausgegeben
werden. Die Puffergröße bleibt konfigurierbar. Vor dem Write wird verfügbarer RAM
mit Reserve geprüft, bevor ein Schreibdeskriptor oder Pending-Marker entsteht.

Jeder mbuffer-Lauf erhält ein eigenes dauerhaftes Statuslog im privaten
State-Verzeichnis. Der Jobfortschritt enthält das angewandte Ratenlimit,
Puffergröße, Vorfüllung, Logpfad und – falls im Log tatsächlich vorhanden – den
zuletzt beobachteten Pufferfüllstand. Parser-Lesezugriffe sind auf einmal pro
Sekunde und die letzten 8 KiB begrenzt. Die gespeicherten Web-Transferwerte sind
bis zur Webintegration weiterhin als vorgemerkt markiert; die laufende
Hardware-Abnahme übergibt ihre geprüften Werte ausdrücklich.

## Sequenzieller Restore-Kandidat

Der neue, noch nicht auf Hardware abgenommene Kandidat liest bei `scan()` zuerst
das Daten-TAR vollständig und danach seinen Prüfbeleg. Archivhash, Bytezahl,
Dateimanifest und alle Datei-Hashes werden weiterhin geprüft; die Receipt-Kette
wird erst mit dem nachfolgenden Beleg bestätigt. Das vermeidet den bisherigen
Sprung zum Beleg und zurück zum Daten-TAR für jedes Paar.

Restore verwendet denselben Prüfpass zum Extrahieren ausgewählter Dateien.
Sie liegen zunächst in einem exklusiv erzeugten privaten `.otam-restore-<UUID>`-
Verzeichnis auf dem Zieldateisystem. Erst nachdem alle vollständigen TAR-Hashes,
Prüfbelege und ausgewählten Dateien einschließlich Ziel-Rücklesung erfolgreich
geprüft sind, werden die Dateien mit exklusiven Hardlinks unter ihren Zielnamen
veröffentlicht. Vorhandene Ziele werden niemals ersetzt. Alle Verzeichniszugriffe
erfolgen relativ zu Deskriptoren mit Symlink-Schutz. Das Ziel muss Hardlinks auf
demselben Dateisystem unterstützen; Fehler bleiben ein fehlgeschlagener Restore.
Bei Prozessabsturz kann das private Verzeichnis zur ausdrücklichen Inspektion
zurückbleiben. Es gibt keine automatische Löschung fremder Restore-Daten.

Jedes Daten-TAR wird dadurch nur einmal vom Band gelesen. Bei bestätigter
Vorwärtsposition verwendet der Adapter relative Filemarks mit anschließender
Positionskontrolle. Unbekannte oder rückwärts liegende Positionen verwenden
weiterhin den konservativen BOT-Pfad. Die laufende große Hardware-Abnahme nutzt
unverändert den vorherigen Code; Linux- und physische Nachtests dieses Kandidaten
stehen noch aus.

## Noch sperrende Abnahmen

Kleine reguläre Zyklen, Append, verzögerte Verifikation, Katalogverlust/Restore und
unabhängige GNU/Linux-Wiederherstellung sind auf dem Testmedium bestanden.

* Große TARs mit Transfersteuerung und dauerhaftem Pufferfüllstandsprotokoll.
* Konservatives Verhalten bei realem Abbruch, Neustart und unklarem Tail.
* CLI-/Web-Medienbindung und geprüfte Aktivierung der gespeicherten Transferwerte.
* Dokumentierte Freigabegrenzen für weitere Medien-/Laufwerksprofile.
