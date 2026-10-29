# OTAM bedienen

OTAM erstellt überprüfbare Dateiarchive auf Band. Es löscht keine Quelldateien.
Ein grünes **VERIFIED** bedeutet: Das gesamte TAR wurde physisch zurückgelesen
und gegen seine vollständige Prüfsumme und die Datei-Prüfsummen geprüft.
Ein geschriebenes, aber noch nicht verifiziertes Archiv ist kein erfolgreicher
Abschluss. Der Simulator verwendet Dateien statt Hardware und zeigt dies an.

## 1. Einrichten und orientieren

Installation und erstes Passwort: [Debian-Anleitung](debian-installation.md).
Unter **Einstellungen** stehen Quellen, Staging und Konten. Administratoren
verwalten Benutzer und Freigaben; Operatoren bedienen erlaubte Archivaufgaben;
Viewer lesen Katalogdaten. Jede Node hat eigene Konten. Einstellungen des
Betriebssystems und NAS-Rechte werden nicht durch einen Browserknopf erweitert.

Die **Übersicht** zeigt den aktuellen Archivplan und direkte Sprungziele zu
Archiven, Dateikatalog, Bandinventar und vorbereiteten Archiven. **Protokolle**
halten Vorgänge und Fehler fest. Quellen, Staging, Bandmedium und Restore-Ziel
sind unterschiedliche Ressourcen.

## 2. Quelle und lokales Staging

Quellen können lokale, USB- oder NAS-Verzeichnisse sein. Sie müssen vom
Dienstkonto lesbar sein. Eine entfernte Quelle ist kein zulässiges Staging.
Staging muss auf geprüftem lokalem persistentem Speicher liegen und beschreibbar
sein. Für Bandarchivierung zunächst den Staging-Speedtest und die passende
Transferkonfiguration durchführen. Vorgemerkte oder veraltete Werte ersetzen
keine gültige, profilgebundene Auswahl.

Bei NFS können IP-Freigabe und Datei-/Verzeichnisrechte verschieden sein.
`Permission denied` verlangt eine Korrektur der Quellrechte, keinen root-Worker.
Fehler nicht durch pauschale Schreibrechte oder stilles Überspringen umgehen.

## 3. Kassette vorbereiten oder wiederfinden

Unter **Hardware** Laufwerk, eingelegte Kassette und Diagnosen prüfen.

Die Übersicht zeigt genau das aktuell erkannte Band mit Laufwerksstatus.
Frühere Erkennungen bleiben aufklappbar unter **Diagnosedaten** erhalten; alle
bekannten Kassetten stehen im **Bandinventar**. Die Anzeige und das Inventar
aktualisieren sich alle fünf Sekunden, auch nach einer Registrierung. Die
Hardwareerkennung erfolgt zwischen Aufträgen; während eines Bandjobs bleiben
die letzten bestätigten Werte sichtbar und werden als solche gekennzeichnet.

- **OTAM-Medium lesend registrieren**: vorhandenen OTAM-Header einlesen und
  zuordnen; Inhalte erhalten. Bei verlorenem Katalog kann zusätzlich eine
  ausdrückliche Katalogrekonstruktion nötig sein, um alle Archive zu erfassen.
- **Band für OTAM vorbereiten**: neue Medien-ID und Header schreiben und
  zurückprüfen. Vorhandene Inhalte werden unbrauchbar. Kein vollständiges
  sicheres Löschen und keine Vollqualifikation des ganzen Bandes.
- **Kassette ausdrücklich neu initialisieren** bzw. **Unterbrochenes Medium
  zurücksetzen**: getrennte, begrenzte destruktive Abläufe. Sie ersetzen keine
  Untersuchung eines ungeklärten Schreibabbruchs und sind nicht allgemein
  verfügbares Recycling beliebiger katalogisierter Medien.

Bei destruktiven Aktionen werden konkrete Laufwerks-/Kassettenidentität und
Bestätigung verlangt. Bekannte bzw. gesperrte Medien werden nicht automatisch
überschrieben. TapeAlert-/Reinigungsanzeigen nicht mit einer OTAM-Initialisierung
verwechseln; die Betriebsanleitung des Laufwerks und passende Reinigungskassette
beachten. Eine Reinigung ist keine Datenverifikation.

## 4. Quellenplan erstellen

Unter **Planung** Quelle, Unterverzeichnisse, TAR-Zielgröße, Staging und
Verifikationsmodus wählen. Ausschlüsse sind exakte relative Pfade mit ganzem
Unterbaum, keine Globmuster. Beispielsweise kann ein Vorschauordner explizit
ausgeschlossen werden. OTAM überspringt Zugriffsfehler nicht still.

Zunächst werden nur Metadaten erfasst, noch ohne Zielkassette. Die Anzeige nennt
bereits gefundene Dateien, Größen und aktuellen Pfad. Der Gesamtumfang ist am
Anfang unbekannt; deshalb zeigt der Balken dann keine erfundene Prozentzahl.
Nach Abschluss Zielmedien in der gewünschten Wechselreihenfolge auswählen.
Die Kapazitätsprüfung berücksichtigt native Kapazität, bereits belegten Platz,
TAR-/Header-/Receiptbedarf und vollständige Dateien. Komprimierungsgewinne werden
nicht vorausgesetzt. Eine große Einzeldatei wird nicht auf mehrere Bänder geteilt.
Reicht die Auswahl nicht, weitere Medien wählen; der Quellenplan bleibt erhalten.

**Medien zuordnen & lokal vorbereiten** startet nach der Kapazitätsprüfung die
Übernahme. Bei ausreichend Staging entstehen lokale TARs und Datei-Prüfsummen
in einem Quelldurchgang. Ein unabhängiger vollständiger lokaler Prüflauf folgt.
Bei zu wenig Platz für alle TARs wird der bisherige Hash-/spätere Stage-Ablauf
verwendet. Die Dateiauswahl ist an ihre ursprünglichen Fingerprints gebunden;
Änderungen erfordern einen neuen Plan. Es gibt keinen atomaren NAS-Snapshot.

## 5. Auf Band schreiben

Den verbindlichen Archivplan öffnen, Medium und Parameter prüfen und
**Archivierung bestätigen** bzw. **Nächstes Medium bestätigen** wählen.
Lokal vorbereitete Quellen starten nicht automatisch einen Bandwrite.

- Archivweise Verifikation: ein TAR schreiben, vollständig prüfen, fortfahren.
- Medienweise Verifikation/Batch: TARs des Mediums vorbereiten, alle schreiben,
  danach vollständig sequenziell zurücklesen. Benötigt Platz für alle diese TARs.

Die geprüften TARs bleiben bis zur vollständigen Rückleseverifikation lokal.
Danach entfernt OTAM ausschließlich seine eigenen registrierten Stagingartefakte.
Byte-/Prozentwerte beziehen sich auf die angezeigte Phase bzw. das aktuelle TAR.
Die Anzeige unterscheidet Kopieren/Hashen, lokale Prüfung, Schreiben, Rücklesen
und Abschluss. 100 Prozent übertragene Bytes allein bedeuten noch nicht VERIFIED.
Dateizähler, aktueller Pfad und MB/s helfen bei der Vorbereitung; eine garantierte
Restzeit gibt es nicht. Das lokale Staging entkoppelt NAS- und Bandgeschwindigkeit.

Bei mehreren Medien wartet der Gesamtjob auf den bestätigten Wechsel. Erst die
angeforderte Kassette einlegen, Identität prüfen und die nächste Etappe bestätigen.
Den ersten Kindjob nicht erneut starten. Bereits laufende Arbeit nicht durch ein
Update, Ausschalten oder weitere Geräteprogramme unterbrechen.

## 6. Suchen und wiederherstellen

**Dateikatalog** durchsucht archivierte Dateien und ihre Kopien. Nach SHA-256
lassen sich identische Inhalte erkennen. Im Restore gewünschte Dateien bzw.
Archive und ein eigenes Ziel wählen, benötigte Kassette einlegen und bestätigen.
OTAM prüft ausgewählte TARs, Dateihashes und Receiptkette; endgültige Dateien
werden erst nach erfolgreicher Prüfung exklusiv veröffentlicht. Bestehende
Zieldateien werden nicht still überschrieben. Selektiver Restore behauptet keine
neue Integritätsprüfung übersprungener alter Nutzdaten.

**Integrität** und explizite Vollprüfung prüfen mehr als eine selektive
Wiederherstellung. Die getrennte Anleitung zur
[Recovery ohne OTAM](recovery-without-otam.md) beschreibt Standard-GNU/Linux-
Werkzeuge; vor schreibenden Befehlen während einer Recovery schützen.

## 7. Fehler, Neustarts und Sicherungen

Nach einem Absturz werden laufende Aufträge als unterbrochen markiert. Es gibt
keine automatische Wiederholung eines unsicheren Bandwrites. Pending-/Tail-
Marker niemals manuell löschen, um eine Sperre zu umgehen. Erst Status und
Protokolle prüfen, Medium identifizieren und den passenden ausdrücklichen
Prüf-/Wiederaufnahmeablauf verwenden. Fehlerberichte und Staging aufbewahren.

Katalog, Control, Konfiguration und Schlüssel regelmäßig sichern. Eine laufende
SQLite-Datei nicht ohne WAL-Zusammenhang kopieren; Backup-API nutzen. Der Katalog
ist aus gültigen Medien rekonstruierbar, aber keine alleinige Sicherung der
lokalen Konten/Steuerdaten. **Synchronisation** kann unabhängige Katalognodes und
Snapshot-Verzeichnisse versorgen; deren Konten werden nicht mitrepliziert.

OTAM archiviert reguläre Dateiinhalte. ACLs, xattrs, Links, leere Verzeichnisse,
vollständige Systemwiederherstellung, Verschlüsselungsverwaltung und beliebige
neue Laufwerksprofile sind nicht pauschal abgenommen. Aktuelle Grenzen stehen
in [production-readiness.md](production-readiness.md) und [tape-format.md](tape-format.md).

## Einen wachsenden Ordner additiv sichern

Bei **Neue Archivierung planen** als Sicherungsumfang **Additiv: nur neue Dateien**
wählen. OTAM vergleicht die Auswahl mit zugeordneten VERIFIED-Archiven derselben
Quelle und Betriebsart. Neue Dateien werden gesichert; bekannte Dateien werden
nicht erneut gehasht. Größe und Änderungszeit dienen zur Erkennung geänderter
Dateien. Für diese kann man **Anzeigen und überspringen** oder **Als neue Version
sichern** wählen. Der Quellenplan zeigt die jeweiligen Anzahlen und geänderten
Pfade vor der Medienzuordnung an.

Die Quellen-ID und das konfigurierte Wurzelverzeichnis müssen zur bisherigen
Sicherung passen. Ohne eindeutig zuordenbare Basis werden alle Dateien gesichert.
Bei gleichen Metadaten können Inhaltsänderungen unentdeckt bleiben; eine
vollständige Sicherung liest und hasht alle ausgewählten Dateien. Gelöschte
Quelldateien bleiben im Archiv. Ohne neue beziehungsweise einzuschließende Dateien
endet der Auftrag ohne Medienanforderung. Bei ausreichendem freien Platz kann man
für die Erweiterung dieselbe Kassette auswählen.

Weitere Details und Grenzen: [Additive Ordnerarchivierung](architecture/additive-backups.md).

## NAS-Vorschauordner

Neue Quellenpläne schließen Verzeichnisse mit dem exakten Namen `.@__thumb`
auf jeder Unterordnerebene automatisch aus. Das verhindert Planungsabbrüche an
NAS-internen Vorschau-Verknüpfungen. Der Quellenplan zeigt die automatisch
übersprungenen Ordner an; die konkreten Ausschlüsse sind im Planhash enthalten
und gelten auch beim Hashen und Staging. Reguläre Dateien gleichen Namens sowie
ähnlich benannte Ordner werden nicht automatisch ausgeschlossen. Andere
symbolische Verknüpfungen werden herstellerunabhängig standardmäßig ebenfalls
übersprungen und mit ihren Pfaden im Quellenplan angezeigt. Alternativ lässt sich
unter **Symbolische Verknüpfungen → Planung anhalten** der strenge Modus wählen.
Linkziele werden niemals verfolgt; reguläre Nutzdateien und andere Fehler wie
fehlende Leserechte bleiben von dieser Regel unberührt.
Bereits gespeicherte Pläne werden nicht nachträglich geändert. Nach einem
fehlgeschlagenen Plan bitte eine neue Quellenplanung starten.

## Optional: Quellen vor der Medienauswahl lokal übernehmen

Der Standardweg bleibt **Quellenplan → Zielmedien zuordnen → TARs lokal
vorbereiten**. Ein fertiges TAR enthält bereits die UUID des Zielmediums.
Eine eingelegte Kassette ist für die lokale Vorbereitung nicht erforderlich;
die Zuordnung vorhandener Medien im Katalog genügt.

Im Quellenplan gibt es zusätzlich den aufklappbaren Schritt **Optional: Quellen
vor der Medienauswahl lokal übernehmen**. Er wird ausschließlich auf ausdrücklichen
Knopfdruck gestartet. OTAM kopiert und hasht dabei die geplanten regulären Dateien
in einen eigenen schreibgeschützten Bereich des lokalen Stagings, ohne Medien
anzufordern oder Bandaktionen auszuführen. Danach können die Zielmedien zugeordnet
werden. Die TARs entstehen aus der lokalen Kopie; das NAS wird nicht erneut gelesen.

Das ist eine zusätzliche Quellkopie, noch kein fertiges Bandarchiv. OTAM prüft vorab
Platz für **Quellkopie plus TARs**. Reicht er nicht, kann der normale Weg mit vorheriger
Medienzuordnung weiterhin genutzt werden. Die Kopie bleibt an Quelle, Auswahl,
Staging und Quellenplan gebunden. Fingerprints und SHA-256 werden bei der späteren
TAR-Erstellung überprüft. Die ursprüngliche Quelle muss weiterhin als Ressource
freigegeben sein, darf nach erfolgreicher Übernahme aber offline sein.

Sobald alle verbindlichen TARs lokal erstellt und geprüft sind, entfernt OTAM
nur die eigenen zusätzlichen Quellkopien. Bei Fehlern oder Prozessabbruch bleiben
unvollständige Daten erhalten; es gibt keine automatische Wiederholung oder
Überschreibung. Bestehende Pläne werden nicht automatisch in diesen Modus versetzt.

## CPU und Transferpuffer (ab 0.8.8)

Die Übersicht zeigt eine Karte **CPU & Transferpuffer**. „CPU Worker“ verwendet
100 % je CPU-Kern; „CPU gesamt“ bezieht sich auf alle Kerne. Daneben steht der
I/O-Warteanteil. Die Werte werden alle fünf Sekunden aus wenigen Zählern gesammelt.
Es gibt keine zusätzlichen Bandabfragen und keine zusätzliche Messhistorie.

Während eines Bandtransfers erscheinen Füllstand und Kapazität des aktuellen
Host-Puffers, auch in den Jobdetails. Lese- und Schreibpuffer sind unterschiedliche
Puffer. Fehlende oder veraltete Messwerte sind ausdrücklich gekennzeichnet.
Die Anzeige verändert die Bandgeschwindigkeit nicht.

## CPU-Reserve beim Rücklesen (ab 0.8.9)

Mit aktivem RAM-Vorlesepuffer werden der TAR-Gesamthash und die Datei-/Strukturprüfung
parallel bearbeitet. Das Band wird weiterhin einmal gelesen; alle Hashprüfungen sind
Pflicht. Die Worker-CPU-Anzeige kann dadurch über 100 % liegen, weil mehr als ein Kern
mitarbeitet. Das ist keine Überlastungsanzeige für die gesamte CPU.

Die systemd-Worker-Unit bevorzugt Archivarbeit moderat bei CPU-Konkurrenz. Andere
Dienste bleiben nutzbar; eine feste Kernausschließlichkeit oder garantierte Bandrate
entsteht dadurch nicht. Große konkurrierende Last und unzureichende Kühlung können
weiterhin bremsen. Bestehende Jobs, Verifikationsmodi und Bandinhalte bleiben unverändert.
