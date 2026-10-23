# Expliziter Reset einer unterbrochenen, nicht katalogisierten Kassette

Ab 0.6.1 gibt es einen separat gegateten Adminworkflow (`physical_reset`,
standardmäßig false; verlangt `physical_initialization`). Er ist ausschließlich
für nicht katalogisierte und nicht gebundene Medien mit erhaltenem, eindeutig
zugeordnetem Pending-Journal vorgesehen. Alle registrierten Medienklassen und
Zustände bleiben geschützt. Dies ist keine allgemeine Recyclingfunktion.

`POST /api/v1/reset/prepare` prüft lesend die konkrete Drive-/MAM-Identität,
natives Profil, Medienklasse und Bezeichnung. Der fünf Minuten gültige Review
bindet zusätzlich SHA-256 und alte Medien-UUID des Pending-Journals. Der normale
Admin-Workerauftrag `reset-physical` benötigt `approval_id`, die exakte Phrase
`RESET <Drive-SN> <MAM-SN>` und `destructive_confirmed: true`. Rolle, CSRF,
einmalige transaktionale Reservation und frische Hardwareprüfung sind Pflicht.

Unter globaler I/O- und Laufwerkssperre wird zuerst ein separater Reset-Guard
mit fsync einschließlich Verzeichnissen persistiert. Erst dann wandert das alte
Pending-Journal bytegleich in die dauerhafte Historie. Der Guard verhindert
Append und normale Initialisierung auch nach Prozessverlust im Übergang.
Ein neuer OTAM-Header mit neuer UUID wird am bestätigten BOT geschrieben;
Dateimarke, EOD mit einer Banddatei, vollständiger Headerhash und Headerinhalt
werden geprüft. Katalog und Medienbindung werden vor Guard-Abschluss publiziert;
das Medium wird erst danach READY. Jeder unklare Zustand bleibt gesperrt.

Der Reset macht die bisherigen logischen Inhalte unbrauchbar. Er ist weder
zertifiziertes sicheres Löschen noch eine neue Vollbandqualifikation. Alte
Pending- und Resetbelege bleiben in `physical-reset-history/` erhalten.
Keine automatische Bereinigung und keine blinde Wiederholung bei Fehlern.

Vor dem realen Reset müssen alle beteiligten Worker die neue Guardlogik kennen.
Solange Reset-Guards bestehen, darf nicht auf eine ältere Version zurückgerollt
werden, die diese Sperren nicht kennt. Konfiguration und SQLite-Datenbanken vor
Installation sichern. Hardwareabnahme und Grenzen stehen in production-readiness.
