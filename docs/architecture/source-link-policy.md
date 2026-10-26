# Verknüpfungen und NAS-Vorschaudaten bei der Quellenplanung

Neue Web-/Queue-Quellenpläne akzeptieren `symlink_policy` mit den Werten `skip`
(Standard) und `error`. Die Regel ist unabhängig von NAS-Hersteller, Protokoll,
Dateiendung und Zielpfad. Datei- und Verzeichnislinks, relative, defekte und
zyklische Links werden bei `skip` nicht verfolgt. Ein ausdrücklich ausgewählter
Pfad durch einen Link führt zur Erfassung des Link-Vorfahren als Ausschluss.
Bei `error` beendet ein Link außerhalb der ausdrücklich ausgeschlossenen Bereiche
weiterhin die Planung. FIFO-, Geräte-, Socket- und Zugriffsfehler werden durch
keinen der Modi pauschal ignoriert.

Zusätzlich werden bekannte NAS-Vorschauverzeichnisse mit dem exakten Namen
`.@__thumb` vor dem Betreten ausgeschlossen. Ähnlich benannte Verzeichnisse und
reguläre Dateien gleichen Namens bleiben enthalten. Weitere Herstellerverzeichnisse
werden nicht anhand vermuteter Namen pauschal entfernt; reguläre Dateien darin
bleiben ohne ausdrücklichen Ausschluss Teil der Sicherung.

Der Quellenplan enthält für übersprungene Links und Vorschauordner jeweils Anzahl
und bis zu 100 Beispielpfade. Sämtliche konkreten Ausschlüsse werden mit dem
ursprünglichen Umfang im Planhash versiegelt und in Medienplanung, Hashing und
Staging verwendet. Mehr als 10.000 konkrete Ausschlüsse verlangen eine kleinere
Auswahl; die Liste wird niemals still gekürzt. Neue Links oder andere Änderungen
nach Abschluss der Vorschau verlangen gegebenenfalls eine neue Quellenplanung.
Das ist ein absichtlicher Schutz der unveränderlichen Auswahl.

Der reguläre Inventarisierer behält ohne ausdrückliche neue Policy den bisherigen
strengen Modus. Gespeicherte Pläne, Hashes und Manifeste älterer Versionen werden
nicht umgeschrieben. Neue Quellenpläne ohne zu sichernde Dateien enden erfolgreich
mit NO_FILES beziehungsweise im additiven Modus NO_CHANGES. Das bestätigt keine
Sicherung der übersprungenen Linkziele und erzeugt keine leeren Archive.

Ein Rebuild aus Band enthält weiterhin die tatsächlich gesicherten regulären
Dateien. Die Linkziele sind nicht Bestandteil der Sicherung; Symlinks selbst
werden im aktuellen Bandformat nicht als restaurierbare Dateisystemobjekte erfasst.
