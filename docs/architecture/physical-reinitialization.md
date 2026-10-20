# Abgeschlossene Initialisierung ohne Katalogeintrag ersetzen

`physical_reinitialization` ist ein separates, standardmäßig deaktiviertes Gate
und verlangt `physical_initialization`. Ein erfolgreicher alter Initialisierungs-
oder Resetbeleg ist dauerhaft gespeichert, auch wenn der Medienkatalog später
bereinigt wurde. Dieser Beleg bedeutet nicht automatisch einen aktiven Fehler.

Die Hardwareansicht nennt die alte Medien-ID und den Zeitpunkt. Der Benutzer
kann das vorhandene Medium lesend registrieren (Inhalte erhalten) oder separat
„Kassette ausdrücklich neu initialisieren“ wählen (Inhalte unbrauchbar machen).
Es gibt kein beliebiges `force=true` und kein pauschales Löschen von Sperren.

`POST /api/v1/reinitialization/prepare` erstellt einen separaten, fünf Minuten
gültigen Adminreview mit exakter Drive-/MAM-Identität, nativem Profil, Label,
Medienklasse und Hashes sämtlicher abgeschlossener Vorgängerfreigaben. Der
Workerauftrag `reinitialize-physical` braucht die genaue Phrase
`REINITIALIZE <Drive-SN> <MAM-SN>` und die destruktive Bestätigung. Die Freigabe
wird vor Gerätezugriff transaktional einmalig verbraucht.

Registrierte oder gebundene physische Medien aller Klassen und Zustände bleiben
geschützt. Pending, Reset-Guards und ungeklärte verbrauchte/unterbrochene/fehl-
geschlagene Schreibfreigaben lassen sich nicht übergehen. Explizite Simulator-
Katalogeinträge werden nicht als physische MAM-Sperre ausgewertet; unbekannte
Altdatensätze bleiben vorsichtig geschützt. Ein bloß gleichlautendes Label
ist keine physische Identität.

Unter den normalen I/O-/Gerätesperren werden Erkennung und Historie frisch
geprüft. Zusätzlich muss der gelesene vorhandene Header zur letzten erfolgreichen
Medien-ID und zur MAM passen. Dann gilt unverändert der geprüfte LinuxTape-
Initialisierungspfad mit bestätigtem BOT, fsynct Pending, neuem Header/UUID,
Dateimarke, EOD und vollständigem physischen Headerhash. Kein alter Payloadread,
keine Vollqualifikation, kein zertifiziertes Löschen. Alte Belege bleiben erhalten.
Fehler nach möglichem Write sperren erneute Neuinitialisierung; kein blindes Retry.

Die reale Prüfung der zweiten Kassette zeigte einen weiteren Fall: bestätigtes
EOD mit null logischen Banddateien trotz erhaltenem altem SUCCEEDED-Beleg.
Ab 0.6.3 erlaubt derselbe explizite Review diesen Zustand ohne erfundenen alten
Header. Bei vorhandenen Dateien muss die alte UUID weiterhin passen. Der neue
Write verlangt unverändert frisches Drive/MAM, bestätigtes BOT, Pending,
Filemark/EOD und vollständigen physischen Headerhash. Null logische Banddateien
bedeuten keine zertifizierte Löschung oder volle Medienqualifikation.
