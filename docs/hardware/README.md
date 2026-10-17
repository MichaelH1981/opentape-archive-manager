# Hardware-Abnahme und lokale Diagnosen

Die Softwaretests verwenden den persistenten Bandsimulator. Der reale Linux-Tape-Adapter ist bis zur ausdrücklich freigegebenen Testband-Abnahme deaktiviert. Kein Softwaretest darf ein physisches Band verändern.

Vorhandene Hardware-Testskripte wurden lesend untersucht und nicht verändert. Die lokalen Diagnoseberichte und Messrohdaten enthalten interne Netzwerkadressen, Benutzerpfade und Geräteseriennummern. Sie bleiben auf dem Entwicklungsrechner erhalten und sind über `.gitignore` vom Repository ausgeschlossen.

## Bisherige Erkenntnisse

- Linux erkennt den Intel-Onboard-SATA-Controller und den separaten IBM/LSI-SAS-HBA. Die System-SSD hängt am Onboard-SATA-Controller.
- Das IBM ULT3580-HH4 wurde erkannt; keine Band-Schreibtests durchgeführt.
- Die interne SSD bestand kurze und lange SMART-Selbsttests, zeigte aber im 30-Minuten-Lesetest erhebliche Durchsatzschwankungen. Ein Kabel-, SSD- oder Controllerdefekt ist damit nicht eindeutig bestimmt.
- Eine zusätzliche HDD wurde über USB 3 rein lesend in drei Bereichen je zehn Minuten geprüft. Durchschnitt außen/Mitte/innen: 149,59 / 138,60 / 88,45 MB/s; CPU-Rechenlast über beide Kerne rund 1–2 %. Drei Transport-Resets verursachten lange Lesepausen. Die HDD besitzt eine historische Medienfehlerlast. Ein interner SATA-Vergleich steht aus.
- Der Betreiber sieht die HDD vorläufig als entbehrlichen Staging-Puffer vor. Quellen bleiben erhalten. Das ist keine abgeschlossene 120-MB/s-Qualifikation.

Verbindliches weiteres Verfahren: [Staging](../staging.md), [Test- und Abnahmeplan](../testing.md), [Risiken](../architecture/risks.md). Physische Schreibtests ausschließlich mit ausdrücklich freigegebenem entbehrlichem Testband. Keine automatische Übernahme destruktiver Funktionen aus Diagnoseskripten.
