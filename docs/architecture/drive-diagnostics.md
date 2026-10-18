# Laufwerksstatus und Diagnosedaten

Die Übersicht des Archive Node zeigt physische Laufwerke und das zuletzt erkannte Medium unabhängig von der gewählten Betriebsart. Das Standalone-Katalogmodul benötigt dafür keine Verbindung zum Bandserver und ruft keine Hardware-API ab.

## Erfassung und Darstellung

Der einzelne Worker erfasst den Gerätestatus etwa alle zehn Sekunden zwischen Aufträgen. Diagnose-Logseiten werden etwa alle 60 Sekunden, bei einem erkannten Medienwechsel oder durch **Hardware → Status & Diagnose aktualisieren** abgefragt. Während eines laufenden Jobs erfolgt kein zusätzlicher paralleler Pollingzugriff. Die Oberfläche liest ausschließlich persistierte Messwerte aus der lokalen Steuerdatenbank; keine Browseranfrage führt einen unmittelbaren Gerätezugriff aus. Ein manueller Aktualisierungswunsch ist ein dauerhafter Workerauftrag und wird nach einem laufenden Job bearbeitet.

Statuswerte: Hersteller/Modell, Firmware, Laufwerksseriennummer, Non-Rewinding-Gerät, zuletzt erkannte MAM-Medienseriennummer, Online-/Tür-/Schreibschutzstatus und bekannte Banddatei-/Blockposition. Eine Position von -1 wird nicht als Block 0 dargestellt. Ein früher erkanntes, nun fehlendes Gerät bleibt als **nicht erreichbar** sichtbar; dessen Medium ist ausdrücklich nur das zuletzt erkannte Medium. Nach 30 Sekunden ohne frische Erkennung bzw. bei fehlendem Worker-Lebenszeichen sind Gerätewerte veraltet. Diagnosen über 120 Sekunden oder ohne aktuellen Gerätekontakt sind ebenfalls veraltet. Ein ausgeschaltetes Laufwerk erzeugt keine erfundenen Diagnosewerte.

Erlaubte SCSI-LOG-SENSE-Seiten über `sg_logs --readonly --raw --maxlen=4096`: 0x2e TapeAlert, 0x02 Schreibfehlerzähler, 0x03 Lesefehlerzähler und 0x0d Temperatur. Es werden keine LOG-SELECT-, Reset-, Modusänderungs-, Datenlese- oder Positionierungsbefehle verwendet. Als zusätzliche Quelle werden vorhandene, fest benannte Statistikdateien des Linux-st-Treibers aus sysfs gelesen.

Fehlerzähler enthalten unterstützte Korrektur-/Wiederholungs-/Bytezähler und unkorrigierte Fehler. Ihr Zählzeitraum ist laufwerksabhängig und kann durch Aus-/Einschalten zurückgesetzt werden. Sie sind keine Messung der verbleibenden Medienlebensdauer und nicht automatisch diesem eingelegten Band zuzuordnen. 64-Bit-Werte werden als Dezimalstrings transportiert und im Browser exakt als BigInt formatiert. Temperaturen mit dem standardisierten Unbekanntwert 255 sowie fehlende/nicht unterstützte Parameter bleiben unbekannt; eine tatsächliche Null wird davon unterschieden.

## TapeAlert und Rohdaten

**Das Lesen der TapeAlert-Seite kann im Laufwerk ausstehende Flags quittieren.** Dies ist ein Verhalten des lesenden Kommandos, kein von OTAM gesendeter Reset. Grundlage: [smartctl, Abschnitt Tape Drives](https://manpages.debian.org/testing/smartmontools/smartctl.8.en.html#TAPE_DRIVES) und [sg_logs](https://manpages.debian.org/testing/sg3-utils/sg_logs.8.en.html).

Jede erhaltene Rohantwort wird deshalb vor dem nächsten Gerätekommando transaktional dauerhaft gespeichert. Für valide TapeAlert-Rohantworten werden aktive Flags bereits in dieser Transaktion übernommen, bevor ein zweiter Verarbeitungsschritt folgt. Die je Laufwerk gespeicherte Flag-Historie enthält erste/letzte Beobachtung und das bei der letzten Geräteerkennung bekannte Medium. Eine später leere TapeAlert-Seite löscht die Historie nicht. Dieser Medienkontext ist ein zeitbezogener Beobachtungswert und kein Nachweis, dass das Medium zwischen getrennten SCSI-Abfragen nicht gewechselt wurde. Es gibt keine automatische Entwarnung oder Löschung der Historie.

Pro Laufwerk werden die neueste Diagnose (maximal vier begrenzte Logseiten), die Historie der bis zu 64 TapeAlert-Flags und der zuletzt beobachtete Gerätestatus gespeichert. Dadurch wächst der Bestand nicht unbegrenzt mit jedem Poll. Unbekannte bzw. fehlerhafte Logparameter werden nicht als Null interpretiert. Abgeschnittene/falsche Logseiten sind ungültig, Rohdaten und Fehler bleiben in der Detailansicht sichtbar. Falls dauerhafte Speicherung scheitert, wird keine weitere Logseite gelesen. Auch Vor-/Nach-Diagnosen eines Wartungsjobs verwenden diesen Speicherweg.

## API und Rechte

- `GET /api/v1/hardware/status`: authentifizierte Statusansicht samt Geräte-/Diagnosezeitpunkten, Aktualität und Workerzustand.
- `GET /api/v1/hardware/diagnostics/{drive_id}`: gespeicherte Diagnose inklusive Rohantworten, Quellen und Flag-Historie; niemals ein direkter Gerätezugriff.
- `GET /api/v1/hardware`: ergänzt die bisherigen Wartungsdaten um dieselbe Statusansicht.
- `hardware-scan`: bestehender Workerauftrag, jetzt einschließlich expliziter Diagnoseabfrage.

Alle Hardware-Routen bleiben auf Archive Nodes beschränkt. Die Web-Unit behält PrivateDevices; nur der bereits separat berechtigte Worker fragt die festen Band-SCSI-Generic-Geräte ab. Ein geänderter SG-Gerätepfad macht eine ältere destruktive Freigabe ebenfalls ungültig.

Softwaretests verwenden ausschließlich synthetische SCSI-Antworten: Seiten-/Längenprüfung, 64-Bit-Zähler, unbekannte Temperaturen, Persistenz nach Rohdatenerfassung, fehlende/nicht unterstützte Seiten, Speicherfehler, Medienwechsel, Offline-/Altdatenzustände sowie Authentifizierung/Rollentrennung. Reale Diagnoseabfragen benötigen ein eingeschaltetes Laufwerk und werden getrennt von den Softwaretests abgenommen. Diese Abfragen schreiben keine Bandnutzdaten; schreibende Wartungsjobs benötigen daneben weiterhin eine ausdrückliche, mediengebundene Freigabe.

Während physischer Wartung zeigt die Übersicht persistenten Transferfortschritt
(Phase, Datenmenge, Durchsatz, Job-ID) aus dem Worker an. Dieser Fortschritt wird
getrennt vom älteren Geräte-/Diagnosestatus auf Aktualität geprüft. Eine frühere
Beobachtung ohne Seriennummer erzeugt nach erfolgreicher Identifikation am gleichen
sysfs-Pfad keine zweite Laufwerkskarte; ihre gespeicherten Rohdaten und TapeAlert-
Hinweise bleiben unter der ursprünglichen ID erhalten. Bereits identifizierte
andere Laufwerke werden dadurch nicht zusammengefasst.

Eine frühere anonyme Beobachtung mit gespeicherten TapeAlert-Hinweisen bleibt
auch nach erfolgreicher Identifikation gesondert sichtbar: Hinweise werden nicht
stillschweigend einem später identifizierten Gerät zugerechnet oder ausgeblendet.
Nur anonyme Einträge ohne gespeicherte Warnungen werden in der Kartenübersicht
zusammengeführt; Rohantworten bleiben weiterhin erhalten.
