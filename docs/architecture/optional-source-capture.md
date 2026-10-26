# Optionale Quellenübernahme ohne Medienbindung

Der reguläre Ablauf bleibt unverändert. `stage-source` ist ein separater
Queue-Auftrag mit genau `job_id` und `source_plan_hash`. Die Weboberfläche bietet
ihn im Quellenplan in einem ausdrücklich optionalen, zunächst geschlossenen
Bereich an. `plan-source` und `bind-plan` lösen ihn nicht automatisch aus.

Ein WAITING_MEDIA-Quellenplan mit unveränderter Freigabe und Staging-Bindung kann
lokal übernommen werden. Die normale Inventarisierung prüft vorher die versiegelte
Auswahl. Der Platztest umfasst Nutzbytes plus geschätzte TAR-Größe. Jede Datei wird
mit sicheren Quellöffnungen, Fingerprints vor/nach Kopie und SHA-256 übernommen,
fsynct und exklusiv veröffentlicht. Die eigenen Dateien sind schreibgeschützt;
ein dauerhafter Owner-Marker bindet das private Verzeichnis an die Quellenplan-ID.
Es werden weder Medien-UUIDs erfunden noch Katalogmedien erzeugt.

Während der Übernahme steht der Quellenjob auf RUNNING/STAGING und protokolliert
Dateien, Bytes und Fortschritt. Erst die vollständige Übernahme publiziert den
neuen versiegelten Quellenplan inklusive Capture-Metadaten und Hashes. Fehler vor
Anlegen eigener Dateien erhalten den Plan zur normalen Medienbindung. Teilkopien
führen zu INTERRUPTED; Workerstart behandelt einen Prozessverlust wie andere
unterbrochene Quellenjobs. Es gibt keine automatische Teilkopien-Wiederverwendung.

Bei der Medienbindung werden die lokalen Fingerprints geprüft. Es müssen genügend
Bytes für alle endgültigen TARs frei sein; kein Rückfall auf die Originalquelle.
Die kombinierte Übernahme akzeptiert innerhalb des Stagings ausschließlich eine
an einen versiegelten Quellenplan gebundene lokale Quellenkopie. Normale
Überschneidungen von Quelle und Staging bleiben verboten. Beim Erstellen jedes
TARs wird der bereits erfasste Datei-SHA-256 erneut verglichen. Die gespeicherte
logische Quelle bleibt für Berechtigungsprüfung und Katalogherkunft erhalten.
TAR-Format, Medien-UUID, Planhash, Receipt- und Rückleseprüfungen bleiben erhalten.

Nach Publikation aller geprüften TARs wird die zusätzliche Quellkopie anhand von
Eigentümer und Fingerprints begrenzt bereinigt. Fehler verschieben die Bereinigung
mit Audit-Ereignis; sie machen einen fertigen TAR-Plan nicht rückwirkend erfolglos.
Die ursprünglichen Quellen, unbekannte Dateien und Hardware-Pending-Journale
werden niemals durch diese Bereinigung entfernt. Inventarlisten und Hashes der
lokalen Einzeldateien werden nicht an die Web-Detailansicht übertragen.
