# Rollierende Sicherungen: Vorschlag für OTAM

Stand: 15. November 2026. Konzept auf Basis des vorhandenen 0.8.9-Codes,
keine implementierte Recyclingfunktion und keine Freigabe zum Überschreiben
vorhandener Medien. Bestehende Archive und Sicherheitsjournale bleiben erhalten.

## Festgelegter erster Funktionsumfang

Rollierende Sicherung bedeutet zunächst wechselnde, vollständig unabhängige
Vollsicherungen auf benannten, erweiterbaren Bandsätzen. Beispielsweise enthält
die Sicherungsregel „Borg NAS“ die Sätze A und B mit jeweils zwei oder mehr
Kassetten. Jeder erfolgreiche Lauf bildet eine neue Backupgeneration. Er benötigt
keine Dateien aus einer früheren Generation oder einem anderen Satz.

Der erste Umfang enthält keine inkrementellen Ketten, automatische Löschung nach
Kalender, automatische Wiederaufnahme nach unklarem Write oder automatische
Freigabe fremder Kassetten. Echte Einzeldateisegmentierung ist eine eigenständige
Erweiterung. Ein Borg-Repository als Verzeichnis aus ausreichend kleinen Dateien
benötigt sie normalerweise nicht.

Die vorhandenen Mehrband-Childjobs und das TAR-/Receiptverfahren bilden die Basis.
Es fehlen jedoch Satzverwaltung, Generationsstatus, Wiederverwendungsfreigabe,
vollständiger Satz-Restore und deren Sicherheitsschnittstellen. Die Medienklasse
allein darf deshalb in der Oberfläche keinen fertigen Rotationsmodus versprechen.

## Begriffe und feste Beziehungen

| Begriff | Bedeutung |
| --- | --- |
| Sicherungsregel | Quelle, Auswahl, Konsistenzverfahren, Aufbewahrung und zugeordnete Bandsätze |
| Bandsatz | Dauerhafter benannter Behälter, etwa „Borg A“; seine Kapazität darf wachsen |
| Kassette | Physisches Medium mit bestätigter Identität, insbesondere MAM-Seriennummer |
| Medien-Inkarnation | Logischer OTAM-Header mit UUID; nach Wiederverwendung neuer Header/neue UUID |
| Backupgeneration | Ein konkreter Vollsicherungslauf mit eingefrorener Quellenaufnahme |
| Generationsvolumen | Die tatsächlich für diese Generation verwendete Kassette und ihre Inkarnation |

Eine Kassette gehört höchstens einem aktiven Bandsatz. Ein Bandsatz gehört im
ersten Umfang genau einer Sicherungsregel. Simulator- und physische Sätze sind
strikt getrennt. Historische Mitgliedschaften bleiben erhalten. Ein Restore
verwendet immer die tatsächlichen Generationsvolumen, niemals die heute eventuell
veränderte Mitgliederliste des Bandsatzes.

Ein Satz ist ein Kapazitätspool; eine Generation muss nicht alle Mitglieder
benutzen. Größere Sätze mit freien Kassetten können zunächst eine neue Generation
auf bisher unbenutzten Mitgliedern aufnehmen. Alte Generationen bleiben dabei
erhalten. Erst notwendiges Recycling verändert deren Verfügbarkeit.

## Beispiel mit zwei wachsenden Bandsätzen

### Konfigurierbare Satzanzahl und Ein-Satz-Betrieb

Die gewünschte Anzahl der Bandsätze ist pro Sicherungsregel konfigurierbar,
beginnend mit einem Satz. Sie ist keine fest eingebaute Zwei- oder Drei-Satz-Regel.
Weitere Sätze lassen sich später hinzufügen, ohne bestehende Generationen neu zu
schreiben. Die gewünschte Satzanzahl reserviert keine Kapazität: Noch nicht mit
genügend geeigneten Kassetten ausgestattete Sätze erscheinen als ausstehend.
Satzanzahl und Kassettenzahl je Satz sind getrennte Einstellungen.

Der Betreiber beschreibt hier einen zusätzlichen rollierenden NAS-Bestand, das
Livesystem sowie die lokale Staging-Kopie während der Bandsicherung. Für diesen
Betriebsfall kann bewusst ein einziger Bandsatz erneuert werden. OTAM verlangt
dabei keine zweite vollständige Bandgeneration. Während der Wiederverwendung ist
der alte Bandstand jedoch nicht mehr als vollständige verfügbare Sicherung zu
zählen; die gewünschte Mindestzahl erhaltener Bandstände während der Erneuerung
ist dann ausdrücklich null. Externe Kopien werden als Betreiberangabe erfasst,
nicht ohne Prüfung als von OTAM verifiziert oder gegen gemeinsame Ausfälle
unabhängig behauptet.

Vor dem ersten destruktiven Schritt muss im Ein-Satz-Modus der gesamte zu
sichernde Quellenstand lokal vollständig übernommen, gehasht und unveränderlich
für den Lauf verfügbar sein; die Existenz einzelner fertig vorbereiteter TARs
reicht nicht. Die Quellenaufnahme bleibt bis zum vollständig verifizierten
Satzabschluss erhalten. Platzbedarf für diese Kopie und gleichzeitig benötigte
TARs wird vorab geprüft; die automatische Quellenkopie-Bereinigung muss für diesen
Modus entsprechend später erfolgen. Fehlender Platz sperrt den Lauf vor dem
Überschreiben. Nach Fehler bleibt die Kopie zur kontrollierten Recovery erhalten.

Die Auswahl „ein Satz“ ändert keine Schutzfrist und keinen manuellen Schutz
stillschweigend. Bei widersprechenden Aufbewahrungsvorgaben zeigt OTAM den
Konflikt vor der Freigabe. Die Oberfläche erklärt knapp: „Während der Erneuerung
kein vollständiger Bandstand verfügbar; vollständige lokale Quellenaufnahme
wird bis zum erfolgreichen Abschluss aufbewahrt.“

Bei Erweiterung von einem auf zwei Sätze wird zuerst der neue Satz vollständig
beschrieben und geprüft; der bestehende Satz bleibt dabei unverändert. Danach
kann die Mindestzahl erhaltener Bandstände bewusst auf eins angehoben werden.
Beim dritten Satz sind entsprechend zwei während der Erneuerung erhaltene
Stände möglich. Das Anlegen zusätzlicher Sätze ändert die Schutzregel nicht
automatisch, OTAM bietet die Anpassung mit erklärter Wirkung an. Beim Verkleinern
bleiben geschützte Inhalte und Historie erhalten; Entfernen aus der aktiven
Rotation ist kein Löschauftrag.

### Wechselbetrieb

| Lauf | Ziel | Geschützter Vorgänger während des Schreibens |
| --- | --- | --- |
| 1 | A, Generation 1 | Noch keiner; ausdrücklich ausgewiesener Erstaufbau |
| 2 | B, Generation 2 | A / Generation 1 |
| 3 | A, Generation 3 | B / Generation 2 |
| 4 | B, Generation 4 | A / Generation 3 |

Bei Lauf 3 darf Generation 1 erst dann zur Wiederverwendung freigegeben werden,
wenn Generation 2 vollständig verifiziert und weiterhin verfügbar ist und die
Aufbewahrungsregeln Generation 1 nicht zusätzlich schützen. Fällt B aus oder ist
sein Zustand ungeklärt, wird A nicht als letzte vollständige Generation geopfert.

Wächst die Quelle von etwa 800 GB auf einen Umfang, der drei Kassetten benötigt,
wird A um eine dritte Kassette ergänzt. B wächst spätestens vor seinem nächsten
Lauf ebenfalls. Die Oberfläche zeigt den Bedarf je Satz; eine Kassette wird nicht
stillschweigend zwischen A und B geteilt. Konkrete Anzahlen entstehen erst aus der
Größenanalyse einschließlich TARs, Belegen und Wiederherstellungsmetadaten.

## Was vorhanden ist und was fehlt

Die Medienklasse `rotation` ist bisher eine Klassifizierung. Sie implementiert
weder Aufbewahrungsfristen noch Zeitpläne oder die Wiederverwendung bekannter
Medien. Initialisierung, Neuinitialisierung und Abbruch-Reset verweigern bewusst
bereits katalogisierte oder gebundene physische Medien.

Die additive Auswahl in `otam/web/additive.py` berücksichtigt alle zugeordneten
verifizierten Archive derselben Quelle und desselben Backends. Sie ist nicht auf
einen Sicherungssatz beschränkt. Eine neue Sicherung auf Satz B könnte deshalb
Dateien überspringen, die nur auf Satz A vorhanden sind. Satz B wäre dann keine
unabhängige Vollsicherung; das spätere Überschreiben von A wäre Datenverlust.

Der aktuelle Vergleich unveränderter Dateien verwendet Pfad, Größe und mtime.
Das beweist keine Inhaltsgleichheit. Geänderte Dateien werden standardmäßig
übersprungen und nur auf ausdrückliche Auswahl eingeschlossen. Ein künftiger
Backupmodus muss Änderungen als neue Version übernehmen oder den Sicherungspunkt
als unvollständig zurückweisen. Übersprungene Inhalte erhalten keinen neuen
SHA-256-Nachweis.

Der Restore stellt ausgewählte Archivkopien wieder her. Ein vollständiger
Verzeichniszustand zu einem Zeitpunkt einschließlich entfernter oder umbenannter
Pfade ist bisher kein eigener Sicherungspunkt. Auch dafür fehlt ein Datenmodell.
`media.generation` bezeichnet derzeit die LTO-Generation, nicht eine
Backupgeneration; dieses Feld darf nicht umgedeutet werden.

## Empfohlene Betriebsarten

Für überwiegend wachsende Foto-, Film- und Musiksammlungen bleibt das dauerhafte
Archiv mit additiven Ergänzungen sinnvoll. Eine zusätzliche unabhängige Kopie
schützt gegen Medienverlust. Regelmäßige Vollkopien nur wegen eines Kalenders
würden unnötig Quellen, Laufwerk und Medien belasten.

Für kleinere, häufig veränderte Bestände ist ein Einstieg mit unabhängigen
Vollsicherungen auf wechselnden Bandsätzen am einfachsten zu prüfen und
wiederherzustellen. Ein Satz kann mehrere Kassetten umfassen. Zeitpunkt und
Aufbewahrung müssen sich nach gewünschtem Datenverlustfenster, Datenmenge und
möglichen manuellen Bandwechseln richten; es gibt hier noch keine festgelegte
tägliche oder wöchentliche Vorgabe.

Für große veränderliche Bestände sind periodische Vollsicherungen mit additiven
Ergänzungen innerhalb derselben Generation die spätere Ausbaustufe. Jeder
Sicherungspunkt hängt dann von einer vollständigen Kette ab. Ein neuer
Generationssatz beginnt wieder vollständig. Generationenübergreifende
Abhängigkeiten sind im ersten Entwurf ausgeschlossen.

## Kapazität und Aufbewahrung

Wer während einer neuen Sicherung jederzeit N vollständige Generationen erhalten
will, benötigt Kapazität für N+1 Generationen. Mit drei ausreichend großen Sätzen
lassen sich nach dem ersten Aufbau zwei abgeschlossene Generationen schützen und
eine dritte erstellen. Drei jederzeit geschützte Generationen benötigen einen
vierten Arbeitssatz. Eine unvollständige oder fehlgeschlagene Generation zählt
nicht als Ersatz für eine geschützte Generation.

Beispiel: Benötigt ein Bestand zwei LTO-4-Kassetten pro Vollsicherung, bestehen
drei unabhängige Sätze aus sechs Kassetten. Wachstum kann weitere Medien erfordern.
Geplant wird anhand tatsächlicher TAR-/Beleggrößen und nativer Kapazität ohne
angenommene Kompressionsgewinne und ohne pauschalen zusätzlichen 5-%-Abzug.

Eine Aufbewahrung kombiniert Mindestanzahl vollständiger Generationen und eine
Mindestdauer. Die jeweils strengere Anforderung gilt. Optional dauerhaft
geschützte Sicherungspunkte verhindern die Freigabe ihrer gesamten Abhängigkeiten.
Datum allein ist kein Überschreibauftrag. Ein Medium ist nur dann geeignet, wenn
kein aufzubewahrender Sicherungspunkt mehr von irgendeinem seiner Archive abhängt.
Einzelne abgelaufene TARs mitten auf einem Band geben keinen nutzbaren Platz frei.

## Vorgeschlagener Ablauf in der Oberfläche

1. Sicherungsregel anlegen: Quelle, Ausschlüsse, Voll-/Ergänzungsmodus,
   Aufbewahrung und zugeordnete Mediengruppe. Dauerarchive sind ausgeschlossen.
2. Quelle inventarisieren und benötigte Kapazität berechnen. Lokale Vorbereitung
   bleibt wie bisher optional vor der Medienzuweisung möglich.
3. OTAM zeigt geeignete neue oder ausdrücklich wiederverwendbare Sätze sowie
   alle Sperrgründe an. Es fordert die konkret benötigten Kassetten nacheinander an.
4. Ein gesonderter Review nennt beim Recycling MAM-Seriennummer, alte logische
   Medien-ID, betroffene Generationen und den vollständigen Inhaltsverlust.
   Erst eine konkrete Bestätigung autorisiert diesen destruktiven Schritt.
5. Batch-Staging bei ausreichendem Platz, zusammenhängendes Schreiben und
   anschließende vollständige physische Prüfung der neuen Archive. Bestehende
   Prüfmodi/Planhashes werden niemals stillschweigend umgestellt.
6. Erst nach erfolgreicher Prüfung aller Teile wird der neue Sicherungspunkt
   vollständig. Die Oberfläche nennt benötigte Medien und bietet den Restore
   dieses Standes in ein neues Zielverzeichnis an.

Das manuelle Einzellaufwerk erlaubt keine unbeaufsichtigte Sicherung über einen
Medienwechsel hinweg. Ein Zeitplan kann einen Auftrag vorbereiten und den
Medienbedarf melden; Einlegen allein erteilt keine Löschfreigabe.

## Neue Kassetten und Kapazitätserweiterung

### Vor Beginn eines Laufs

Die Quellenanalyse erfolgt vor der endgültigen Medienzuweisung. OTAM zeigt
Nutzdaten, erwartete TAR-/Receipt-/Manifestgrößen, verwendbare Satzkapazität und
Fehlbetrag getrennt an. „Weitere Kassette zu Satz A hinzufügen“ öffnet einen
eigenen Vorgang: Identität erkennen, bekannte Inhalte/Sperren darstellen und
gegebenenfalls ausdrücklich initialisieren oder sicher wiederverwenden.
Einlegen allein ändert weder Mitgliedschaft noch Bandinhalt.

Nur bestätigte nutzbare Kapazität zählt. Neue Kassetten dürfen größer sein als
bisherige, sofern Laufwerk und Profil sie unterstützen; OTAM rechnet pro Medium.
Unbekannte Kapazität ist kein freier Platz. Medienverlust oder fehlende aktuelle
Diagnosen werden als solche angezeigt, ohne während anderer Bandarbeit neue
Geräteabfragen zu starten.

Reicht der Satz nicht aus, bleibt der Lauf vor jedem destruktiven Schritt in
`WAITING_CAPACITY`. Die Oberfläche nennt fehlende Bytes und geeignete
Kapazitätsoptionen. Kein automatisches Ausweichen auf den anderen geschützten Satz.
Eine gescheiterte Packheuristik wird von einer rechnerisch zu kleinen Kapazität
unterschieden: kleinere TAR-Zielgrößen dürfen vor dem Schreiben angeboten werden.
Eine zu große Einzeldatei wird ausdrücklich benannt; weitere kleine Kassetten
lösen deren Problem ohne Segmentierungsfunktion nicht.

Ist die nächste passende Kassette nur noch nicht eingelegt, lautet der Zustand
`WAITING_MEDIA`, mit Satzname, Generationsname, Bandnummer und erwarteter Identität.
Das ist ein anderer Fall als fehlende Gesamtkapazität.

### Nach Planung oder während eines Laufs

Mitglieder lassen sich einem Satz jederzeit hinzufügen, aber eine laufende
Generation erhält dadurch nicht stillschweigend einen anderen Plan. Vor dem
ersten Write kann eine neue Planrevision alle Zuweisungen neu berechnen;
vorherige Reviews verfallen. Bereits erzeugte mediengebundene TARs müssen bei
geänderter Medien-UUID neu gebaut und geprüft werden.

Nach dem ersten Write dürfen erledigte oder bereits freigegebene Teilpläne nicht
umgeschrieben werden. Eine Erweiterung ist nur an einem nachgewiesen untätigen
Medienwechselpunkt ohne offenen Pending-/Receiptzustand zulässig. Sie erzeugt eine
neue, gehashte Fortsetzungsrevision, die Vorgängerhash, unveränderten erledigten
Präfix und genau die neu zugewiesenen ungeschriebenen Archive enthält. Derselbe
eingefrorene Quellenstand gilt weiter. Alte Planhashes und VERIFIED-Ergebnisse
bleiben unverändert. Neue/umgebundene TARs werden erneut vorbereitet; bereits
verifizierte Nutzdaten werden dafür nicht erneut gelesen.

Die derzeitigen `archive-set`-Pläne sind statisch gehasht. Dieser
Fortsetzungsmechanismus ist neu zu implementieren; bloßes Ändern ihrer `children`
oder `media_ids` wäre unsicher. Bis er vollständig getestet ist, ist Erweiterung
nur vor dem ersten Write verfügbar. Die bestehende Grenze von 32 Medien je
Archivsatz ist im ersten Umfang eine sichtbare Validierungsgrenze, keine
unbegrenzte Erweiterbarkeitszusage.

Ein unerwartetes EOM während eines TAR-Writes ist ausdrücklich kein sauberer
Medienwechselpunkt. Der aktuelle Fehler-/Pendingpfad greift, der betroffene TAR
bleibt unbestätigt. Weder die Kassette noch der TAR wird blind weiterbeschrieben;
eine spätere kontrollierte Recovery/Neuplanung braucht einen eigenen Review.

Mitglieder mit noch geschützten Inhalten können nicht entfernt oder in einen
anderen Satz verschoben werden. Unbenutzte, unreservierte Mitglieder dürfen
ausgetragen werden, ohne irgendeinen Bandwrite. Weniger benötigte Kassetten
werden bei einem späteren Lauf übersprungen und niemals vorsorglich gelöscht.

## Auswahl, Aufbewahrung und Freigabe

Der Planer bevorzugt einen leeren geeigneten Satz, danach den Satz mit der
ältesten freigabefähigen Generation. Er zeigt die Entscheidung an, statt blind
zwischen A und B umzuschalten. Pro Sicherungsregel ist höchstens ein schreibender
Generationslauf aktiv; aktive Restores reservieren ihre benötigten Inkarnationen
gegen Wiederverwendung. Reservierungen gelten auch über Medienwechsel hinweg.

Die Regel unterscheidet „gewünschte abgeschlossene Stände“ und „mindestens
verfügbare vollständige Stände während einer Erneuerung“. Für zwei Sätze wären
beispielsweise zwei gewünschte Stände und einer als harte Untergrenze möglich.
Wer zwei Stände jederzeit fordert, benötigt einen dritten ausreichend großen Satz.
Der Erstaufbau unterhalb der Untergrenze wird gesondert ausgewiesen und erlaubt
nur freie/neue Medien, niemals das Opfern einer vorhandenen geschützten Sicherung.

Eine zusätzliche Mindestdauer oder ein manueller Schutz kann auch den ältesten
Satz sperren. Dann lautet die Lösung warten, Kapazität ergänzen oder die Regel
bewusst neu prüfen; OTAM verkürzt keine Aufbewahrung automatisch. Ein erfolgloser
neuer Lauf verschiebt keine Frist des weiterhin geschützten Vorgängers.

„VERIFIED“ beweist eine erfolgreiche frühere Prüfung, nicht die heutige Existenz
einer verschollenen Kassette. Als Ersatz zählen nur vollständige, laut Katalog
verfügbare und nicht beschädigt/verloren gemeldete Generationen. Alter der letzten
physischen Prüfung und externe Lagerung bleiben sichtbar. Es gibt keine große
erneute Vollprüfung aller Vorgänger vor jedem Lauf.

## Sichere Wiederverwendung

Aufbewahrungsentscheidung, Benutzerfreigabe und Geräteoperation sind getrennte
Schritte. Die Freigabe bindet die konkrete physische Seriennummer, bisherige
Header-ID, betroffene Archive, Regelstand und Frist. Unmittelbar vor dem ersten
möglichen Write werden diese Bedingungen unter globaler I/O- und Gerätesperre
erneut geprüft. Zwischenzeitliche Änderungen machen den Review ungültig.

Aktive Jobs, geschützte Abhängigkeiten, unklare Identität, Schreibschutz sowie
offene Pending-/Reset-/Recyclingzustände verhindern die normale Wiederverwendung.
Ein ungeklärter Schreibabbruch braucht weiterhin einen eigenen Recoverypfad;
Retention darf dessen Sperren nicht umgehen.

Ein dauerhaftes Recyclingjournal muss vor dem ersten möglichen Write gesichert
sein. Ab diesem Zeitpunkt darf der alte Inhalt nicht mehr als verfügbarer Restore
oder additive Basis erscheinen. Ein neuer Zustand wie `RECYCLING` muss deshalb
von sämtlichen Katalogkonsumenten berücksichtigt werden; die heutige alleinige
Ausnahme von `SUSPECT`/`RETIRED` in der additiven Auswahl reicht dafür nicht.

Die physische Kassette behält ihre MAM-Seriennummer, erhält bei erfolgreicher
Wiederverwendung aber eine neue logische OTAM-Medien-UUID. Alte Generationen und
Prüfberichte bleiben als Historie erhalten und werden als nicht mehr verfügbar
ausgewiesen. Ihre früheren VERIFIED-Ergebnisse sind historische Nachweise und
kein aktuelles Verfügbarkeitsversprechen. Kein Löschen von Katalogzeilen, um die
bestehenden Schutzprüfungen zu umgehen.

Nach Prozessverlust bleibt der Zustand konservativ gesperrt. Keine automatische
Wiederholung, keine automatische Markerbereinigung und keine Behauptung, alte
Inhalte seien nach einem möglichen Write noch wiederherstellbar.

## Datenmodell und Wiederherstellung

Eigene Entitäten sind erforderlich für Sicherungsregeln, Mediengruppen,
Backupgenerationen, Sicherungspunkte, deren Archiv-/Dateiversionsabhängigkeiten
und Recyclingfreigaben/-intents. Die bestehende LTO-Generation bleibt unverändert.

Ein Sicherungspunkt braucht ein vollständiges logisches Dateiverzeichnis mit
Referenzen auf die konkreten gesicherten Versionen. Bei Ergänzungen dokumentiert
es auch inzwischen entfallene Pfade. Dadurch kommen beim Restore keine Dateien
zurück, die im gewählten Stand bereits entfernt waren. Ältere geschützte Stände
behalten ihre Versionen. Die Quelle wird durch Aufbewahrung oder Restore niemals
automatisch bereinigt.

NAS-Inventarisierung ist ohne Quellsnapshot kein atomarer Zeitpunkt. Änderungen
während der Erfassung müssen weiterhin erkannt und als Fehler oder ausdrücklich
dokumentierte Einschränkung behandelt werden. Ein Manifest macht aus einer
laufend veränderten Quelle keinen transaktionalen Snapshot.

Sicherungspunkt-Manifeste müssen auch außerhalb des lokalen Katalogs gesichert
werden. Eine reine Rekonstruktion vorhandener TARs stellt sonst zwar Dateien,
aber nicht notwendigerweise die Auswahl und Löschsemantik eines Standes wieder her.
Format und Wiederaufbau dieser Manifeste sind vor Freigabe festzulegen.

## Borg-Repository als erster konkreter Anwendungsfall

Ein Lauf verwendet einen vollständigen, konsistenten Repository-Stand, niemals
eine globale additive Auswahl. Die tatsächlich installierte Borg-Version bestimmt
die unterstützte Lock-/Snapshotintegration. Die erste Umsetzung unterstützt
ausdrücklich bereitgestellte unveränderliche Quellenstände; sie behauptet nicht,
eine normale laufende Verzeichniskopie sei ein Snapshot.

Eine spätere integrierte Übernahme hält die Borg-Sperre entweder während einer
vollständigen lokalen Übernahme oder während der Erstellung eines geeigneten
Dateisystem-Snapshots. Erst nach erfolgreicher Übernahme/Abgrenzung wird Borg
wieder freigegeben. Die Sperre muss nicht während des Bandschreibens bestehen
bleiben. Eine unveränderliche lokale Kopie und alle gleichzeitig gestagten TARs
benötigen zusammen entsprechend mehr HDD-Platz; Platz wird vorab geprüft. Ein
Quellenstand darf nicht gelöscht werden, solange noch ungeschriebene Teile von ihm
abhängen. Beliebige frei eingegebene root-Shellhooks sind kein Bestandteil des
Workflows.

Der Restore läuft in ein neues, leeres Ziel. OTAM prüft alle zum Satz gehörenden
Dateien und die exakte Vollständigkeit des Repository-Bestands. Eine Prüfung mit
der passenden Borg-Version ist ein zusätzlicher anwendungsspezifischer Nachweis;
physische SHA-256-Prüfung allein beweist keine Borg-interne Konsistenz. Ein aus
der gesperrten Quelle mitkopierter Lock wird nur nach dokumentierter Prüfung auf
der isolierten Restorekopie behandelt, niemals automatisch auf der Livequelle.
Borg-Schlüssel und Passphrase brauchen einen getrennten sicheren Recoverypfad.

## Recoveryformat ohne OTAM

Die Nutzdaten bleiben unabhängige PAX-TARs, keine nur von OTAM lesbare
Mehrbanddatei. Eine Versionierung des Satzformats definiert Generations-ID,
Quellenstand-ID, Dateiverzeichnis mit Größen/Hashes, Archiv-IDs, Medien-UUIDs,
physische Identitäten und Reihenfolge. Eine Anleitung beschreibt Entpacken,
Vollständigkeitsprüfung und Borg-Prüfung auf Linux/macOS. SHA-256 dient der
Integritätsprüfung; Schutz gegen absichtlichen Austausch der Manifeste erfordert
zusätzlich eine separat vertrauenswürdig aufbewahrte Prüfsumme oder Signatur.

Jedes beschriebene Medium erhält im normalen sequenziellen Schreibablauf
Generationsidentität, lokalen Volumenindex und Recoveryanleitung. Ein
Fortsetzungsverweis erlaubt, das nächste tatsächliche Medium über dessen
Metadaten zu identifizieren. Das letzte Volumen enthält den abschließenden
Gesamtindex einschließlich der verwendeten Planrevisionen. Frühere Volumen müssen
für eine Erweiterung nicht zurückgespult und nachbeschrieben werden. Ihre
Metadaten dürfen deshalb keinen später veralteten Gesamtindex als endgültig
ausgeben. Die vollständige Rekonstruktion darf die Vereinigung der lokalen
Indizes aller benötigten Volumen verlangen.

Ein dauerhaftes Abschlussobjekt bindet die tatsächlich geschriebenen Archive
und Manifeste. Es wird nach den Nutzdaten und ihren Receipts geschrieben und
physisch geprüft; es darf vorab keine erfolgreiche Prüfung versprechen. Erst
danach und nach erfolgreicher Datenverifikation publiziert der Katalog die
Generation atomar als vollständig. Bei Verlust des letzten Mediums bleibt der
gesamte Satz unvollständig; vorhandene normale TARs sind trotzdem einzeln lesbar.

Neue Index-/Abschlussobjekte müssen explizit in Headerformat, Banddateizählung,
Kapazitätsrechnung, Receiptkettenprüfung, Rebuild und Restore implementiert werden.
Die bestehende Annahme „Header plus Daten/Receipt-Paare“ darf nicht durch
zusätzliche unerkannte Banddateien verletzt werden. Ein separater Formatstand und
getestete Versionskompatibilität sind Freigabebedingung. Alte Formate bleiben
lesbar; ältere Worker dürfen neue Formate sicher ablehnen.

## Zustände und Oberfläche

| Generationsstatus | Bedeutung |
| --- | --- |
| PREPARING | Quellenstand wird erfasst und geplant |
| WAITING_CAPACITY | Der gewählte Satz benötigt zusätzliche nutzbare Kapazität |
| WAITING_APPROVAL | Wiederverwendung ist geeignet, aber noch nicht autorisiert |
| WAITING_MEDIA | Eine konkret benannte, bereits zugewiesene Kassette fehlt im Laufwerk |
| RUNNING | Staging, Schreiben, Prüfen oder Abschluss läuft; Phase separat sichtbar |
| VERIFIED | Alle erforderlichen Teile und der Satzabschluss sind bestätigt |
| FAILED / INTERRUPTED | Kein vollständiger neuer Sicherungsstand; Details und Artefakte bleiben |
| UNAVAILABLE | Historischer Stand ist wegen Überschreiben, Verlust oder Defekt nicht vollständig verfügbar |

Die Satzübersicht zeigt Name, Mitglieder, bestätigte Kapazität, letzte vollständige
Generation, Schutzfrist, aktuellen Lauf und konkreten Erweiterungsbedarf. Aktionen
sind „Sicherung planen“, „Kassette hinzufügen“, „Stand wiederherstellen“ und bei
Eignung „Wiederverwendung prüfen“. Farben allein reichen als Begründung nicht.

Die Laufansicht nennt aktuelle Kassette, nächste erwartete Kassette, vorbereitete,
geschriebene und verifizierte Bytes/TARs sowie Gesamtfortschritt mit klarem Bezug.
Wartezustände haben eine konkrete Handlungsanweisung. Kein Zeitplan startet
zusätzliche konkurrierende Läufe, während der vorige auf Bandwechsel wartet.

## Persistenz und Kompatibilität

Vorgeschlagene getrennte Entitäten: `backup_policies`, `tape_sets`, zeitlich
versionierte `tape_set_members`, `backup_generations`, `generation_volumes`,
`generation_plan_revisions` und `recycle_intents`. Die Vollmanifest-Referenzen
werden mit ihren Hashes gesichert. Namen ersetzen niemals UUIDs als Identität.
Backend und Nodezuordnung sind Teil der Validierung.

Die wiederherstellungsrelevanten Metadaten gehören in den versionierten Katalog
und seine signierte Synchronisation, nicht ausschließlich in einen lokalen
Control-Key. Queue, Benutzersitzungen und kurzfristige Freigaben bleiben im
Control. Katalog und Control können nicht gemeinsam atomar committen: dauerhafte
Operations-IDs, einmaliger Verbrauch und abgleichbare Intents müssen ein
zweiphasiges, nach Absturz gesperrtes Verfahren erlauben. Ein fehlendes
Gegenstück ist ein Prüfzustand, keine automatische Write-Erlaubnis.

Migrationen ändern weder alte Planhashes noch bestehende Archive. Bestehende
Medien werden nicht allein wegen `class=rotation` in Sätze übernommen oder zum
Recycling freigegeben. Benutzer ordnen sie ausdrücklich zu; ihre bisherigen
Inhalte bleiben geschützt. Neue Schema-/Formatstände verlangen Backup,
Kompatibilitätstests, Versionsgate und dokumentierten Rückweg vor dem Deployment.

## Umsetzung in überprüfbaren Schritten

1. Regel-/Generationsmodell und rein lesende Freigabevorschau mit verständlichen
   Sperrgründen; zunächst unabhängige Vollgenerationen und keine Bandwrites.
2. Separat gegateter Recyclingworkflow für bekannte Medien mit Historie,
   dauerhafter Reservation, neuer UUID und frischer Identitätsprüfung.
3. Vollständige Generationsjobs, Restorepunkt-Manifeste und Gesamtstatus über
   mehrere Medien. Erst danach reale Abnahme auf ausdrücklich entbehrlichen Medien.
4. Generationsgebundene Ergänzungen, Kettenaufbewahrung und zeitgesteuerte
   Vorbereitung. Keine globale additive Basis für unabhängige Generationen.

Für den ersten produktiven Umfang müssen die Schritte 1–3 gemeinsam abgenommen
sein. Erweiterung vor Write ist Bestandteil dieses Umfangs. Versionierte
Fortsetzung nach einem erfolgreichen Medium folgt als getrennt geprüfte
Erweiterung; bis dahin wird diese Aktion ausdrücklich gesperrt. Zeitpläne können
später hinzukommen, der manuelle Ablauf ist vollständig ohne sie nutzbar.

Konkrete Abnahmekriterien:

- A vollständig, B scheitert: A bleibt lesbar und geschützt; B wird nicht gezählt.
- A wird nach erfolgreichem B erneuert: B bleibt unverändert; nach möglichem
  Überschreiben wird der alte Stand von A niemals weiter als verfügbar angeboten.
- Aufnahme eines neuen Satzmitglieds verändert keine historische Medienliste.
- Kapazitätsmangel vor Start führt zu keinem Write; zusätzlicher Platz löst einen
  neuen prüfbaren Plan aus, keinen Eingriff in einen geschützten anderen Satz.
- Erweiterung an sauberem Wechselpunkt erhält alle erledigten Planhashes und
  Datenprüfungen; Pending/EOM verhindert diese Erweiterung.
- Dauer-/Anzahlschutz, aktive Restores und manuelle Sperren verhindern Recycling.
- Zwei konkurrierende Freigaben reservieren nie dieselbe Inkarnation; erneute
  Queuezustellung verursacht keinen zweiten Headerwrite.
- Restore ohne OTAM-Datenbank und ohne OTAM-Programm rekonstruiert aus allen
  benötigten Volumen exakt den Vollbestand; falsche/fehlende Medien und manipulierte
  Manifeste werden erkannt. Ein kleines echtes Borg-Testrepo besteht anschließend
  die passende Borg-Prüfung; Schlüsselabhängigkeiten sind dokumentiert.
- Datenbank-/Prozessfehler vor und nach Headerwrite/Abschluss werden einzeln
  provoziert. Es gibt weder stillschweigende Wiederholung noch falsche Vollständigkeit.

Abnahmetests müssen insbesondere das Scheitern der letzten Kassette, fehlende
Kettenmedien, Dateilöschungen/-änderungen, aktive Restores, falsche MAM, geänderte
Freigaben, Katalogverlust und Prozessverlust vor/nach dem ersten möglichen Write
umfassen. Ein Fehler darf weder die Mindestzahl geschützter Generationen reduzieren
noch alte Archive als weiterhin verfügbar ausweisen, nachdem sie überschrieben
worden sein könnten. Große redundante Hardwaretests sind dafür nicht erforderlich.

## Vergleichbare Grundsätze

Bareos und Bacula trennen ebenfalls Aufbewahrung, Katalogabhängigkeiten und
Wiederverwendung von Volumes. OTAM sollte diese Grundsätze übernehmen, aber die
konkrete destruktive Freigabe für den manuellen Betrieb sichtbar halten:

- [Bareos: Volume Management](https://docs.bareos.org/TasksAndConcepts/VolumeManagement.html)
- [Bacula: Automatic Volume Recycling](https://www.bacula.org/15.0.x-manuals/en/main/Automatic_Volume_Recycling.html)
