# Quellenplanung vor Medienzuordnung

Ab 0.7.0 erstellt die Weboberfläche zuerst einen Quellenplan (`plan-source`).
Er benötigt Quelle, Auswahl, TAR-Zielgröße, Verifikationsmodus und lokales
Staging, jedoch kein Zielmedium und kein eingelegtes Band. Es werden nur
Dateimetadaten gelesen. Der Plan enthält Größen, TAR-Schätzungen, größte
vollständige TAR-Datei und stabile Dateifingerprints; keine Dateiprüfsummen,
keine Medien-UUID und kein erzeugtes TAR.

Ein dauerhaft gespeicherter `source-plan` wartet in `WAITING_MEDIA`. Die
Oberfläche fordert danach Zielmedien an. `bind-plan` bindet die unveränderte
Quellenplan-SHA-256 und die geordnete Medienliste. Die konservative Kapazität
(native Kapazität minus Belegung; ab 0.7.3 ohne pauschale Prozentreserve) wird einschließlich kompletter
TARs und Receipts vor jedem Inhaltsread geprüft. Reicht sie nicht, bleibt
der Quellenplan mit verständlichem Hinweis erhalten. Zusätzliche oder andere
Medien lassen sich ohne erneutes Hashen wählen. Große Einzeldateien werden
nicht auf mehrere Bänder geteilt; deren vollständiges TAR muss auf ein Medium
passen. Der frühere direkte Planungsaufruf hat dieselbe Größen-Vorprüfung.

Erst nach ausreichender Kapazität werden Quelle/Auswahl erneut geprüft und
Dateiinhalte gehasht. Vor jedem Hash muss der ursprüngliche Fingerprint aus
Gerät, Inode, Größe, mtime und ctime passen. Änderungen, zusätzliche oder fehlende
Dateien erfordern einen neuen schnellen Quellenplan. Der Übergang reserviert
den Quellenplan; Doppelbindung und parallele Wiederverwendung werden abgewiesen.
Prozessverlust bleibt als unterbrochen erkennbar. Der ursprüngliche Quellenplan
bleibt nach erfolgreicher Bindung mit Verweis auf den verbindlichen Ein-/Mehrband-
Archivplan gespeichert (`BOUND`). Erst dieser geprüfte Plan darf ins Staging.

Das physische TAR-Format bleibt unverändert. Staging benötigt weiterhin den
mediengebundenen Archivplan, aber keine eingelegte Kassette. Vor echtem Schreiben
prüft der bestehende Pfad erneut Drive/MAM, Header/EOD, Receiptkette, Pending,
Stagingintegrität und gespeicherte Transferwerte. Ein Quellenplan ist weder
Inhaltsverifikation noch eine Garantie für den Zustand eines physischen Bandes.
Es wurde für diese Planungsänderung kein großer Bandtest wiederholt.

## Ab 0.7.1: ausdrückliche Ausschlüsse

`excluded_paths` enthält exakte relative Pfade; ein Ordner schließt seinen
Teilbaum ein. Keine Globmuster und kein Verfolgen externer Symlinks. Ausschlüsse
werden im Quellenplan versiegelt, angezeigt, vor jedem Inhaltsread berücksichtigt
und in alle verbindlichen Kindpläne übernommen. Die Bindung akzeptiert keine
nachträgliche Änderung. Die Quellen bleiben unverändert. Nicht ausgeschlossene
Symlinks oder andere ununterstützte Dateitypen brechen sicher ab. Ausschlüsse
sind kein stillschweigendes Überspringen von Fehlern.

Ab 0.7.2 zählt die Gruppierung den bytegenauen Schätzbedarf linear je Eintrag,
statt beim Hinzufügen jeweils die bisherige Gruppe erneut zu serialisieren.
Die Kapazitätsgrenzen bleiben unverändert. Grenzwerte, Unicode-Pfade und lineare
Arbeit sind softwaregeprüft; der echte 30.800-Dateien-Quellenplan brauchte 11,59 s.

## Ab 0.7.3: native Kapazität und vollständige TAR-Verteilung

Die feste 5-%-Reserve entfällt in Vorplanung, verbindlicher Planung und
Schreibprüfung gleichermaßen. Hardwarekomprimierung bringt keinen geplanten
Kapazitätsbonus. Header, bestehende Belegung sowie konservativ geschätzte TAR-,
Metadaten- und Receiptbytes bleiben berücksichtigt. Native Kapazität ist keine
Garantie für ein verschlissenes oder fehlerhaftes Medium: frühes EOM bleibt ein
Fehler mit dauerhaftem Pending und gesperrtem unbestätigtem Tail.

Eine gemeinsame deterministische Largest-first/Best-fit-Zuordnung verteilt ganze
TARs vor dem Hashen; pro Medium bleibt deren ursprüngliche Reihenfolge erhalten.
Die gewählte Medienreihenfolge bleibt die Wechselreihenfolge. Ordered Next-fit
bleibt Rückfall, falls diese Heuristik scheitert. Ein Fehlschlag ist kein Beweis,
dass mathematisch keine andere Packung existiert; die Oberfläche benennt dies.
Der gespeicherte LP-Quellenplan mit 17 TARs und 1.522.733.735.390 geschätzten Bytes
passt softwareseitig auf zwei native 800-GB-Medien ohne Komprimierungsannahme.
Keine Bandbewegung oder neue Bandqualifikation für diese Änderung erforderlich.


## Ab 0.8.5: kombinierte Quellenübernahme bei ausreichend Staging

Die Metadatenvorplanung bleibt unverändert vor der Medienwahl. Die Bindung
verbindet nach ausreichender Medien-/Stagingkapazität Inhalts-Hashing und
TAR-Erstellung. Details zu privater Manifestfinalisierung, einer unabhängigen
Vollprüfung, unveränderten READY-TARs und dem Platzmangel-Rückfall:
[combined-source-capture.md](combined-source-capture.md). Bestehende Pläne
werden nicht nachträglich umgestellt. Planung kann nun bereits alle lokalen
TARs vorbereiten; das ist ausdrücklich auf dem Bestätigungsknopf benannt.
