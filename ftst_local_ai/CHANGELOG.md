# 0.1.1

- Optionales lokales Bildmodell `gemma3:4b` mit eigener Vorbereitung und separater Download-Versuchsnummer.
- Vorhandene Textmodelle und alte Konfigurationen bleiben verwendbar; das Update lädt von selbst kein Bildmodell.
- Downloads erfolgen nacheinander, jeweils höchstens 45 Minuten. Start ab 6 GiB freiem Speicher, Abbruch unter 2 GiB Reserve oder bei mehr als 5 GiB zusätzlichem Speicherverbrauch je Versuch.
- Deutsche Beschriftungen für die Vorbereitung; kein Cloud-Fallback, weiterhin nur ein geladenes Modell und eine Generierung gleichzeitig.

# 0.1.0

- Separater Ollama-CPU-Pilot mit persistenten Modellen und interner API.
- Modellvorbereitung nur nach ausdrücklicher Konfiguration; kein Download bei jedem Neustart.
- Cloudfunktionen ausgeschaltet; begrenzte Parallelität und kurzer Modellaufenthalt im RAM.
