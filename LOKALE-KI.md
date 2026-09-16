# Lokale Textanalyse ab 0.6.0

Die zusätzliche App **FTST Lokale KI** stellt Ollama und das kleine Textmodell `qwen3:4b` im internen Home-Assistant-App-Netz bereit. Die Angebots-App nutzt `http://76b650ab-ftst-local-ai:11434`. Kein öffentlicher Port und keine Home-Assistant-Gerätesteuerung sind dafür nötig. Die offizielle Home-Assistant-Ollama-Integration muss nicht zusätzlich eingerichtet werden, weil die Angebots-App direkt auf den Dienst zugreift.

## Verwendung

1. FTST Lokale KI installieren, starten und das Modell nach deren Dokumentation einmalig vorbereiten.
2. In FTST AngebotsDesigner ist die neue Option `ai_provider` standardmäßig `ollama`. `openai` ist eine bewusste alternative Einstellung und benötigt einen eigenen API-Schlüssel. Bei lokalem Fehler wird nicht auf OpenAI umgeschaltet.
3. Auf der Startseite **Lokale KI prüfen** öffnen: Erreichbarkeit und Modellinstallation werden angezeigt. **Lokale KI mit diesem Beispiel testen** verwendet nur den sichtbaren fiktiven Text und erzeugt keine Projekte, Kunden oder Angebote.
4. In einem Projekt Textnotizen speichern, dann **Gespeicherte Eingaben analysieren**. Der lokale Pilot nimmt maximal 4000 Zeichen und unterstützt zunächst keine Bilder oder Audio. Projekte mit solchen Anhängen werden ausdrücklich abgewiesen, damit nichts unbemerkt fehlt.
5. Zusammenfassung, Mengen und Belege prüfen. Artikel und Preise werden wie bisher anschließend aus Billomat zugeordnet. Eine erfolgreiche KI-Antwort ist keine fachliche Freigabe.

Wiederholte Analyse desselben lokalen Textstands verwendet pro Projekt ein gespeichertes Ergebnis. **Bewusst neu analysieren** überspringt dies. Änderungen an Notizen, interner Promptversion oder installiertem Modelldigest verhindern Wiederverwendung. Vor Wiederverwendung wird das lokale Modell verifiziert. Ohne erreichbaren Dienst bleibt das bisherige Ergebnis sichtbar, eine erneute Analyse meldet den fehlenden Dienst.

## Ressourcen und Fehler

Eine lokale Anfrage gleichzeitig; Kontext 4096, maximal 1200 Ausgabetokens, zwei CPU-Threads, Modellhaltezeit 60 Sekunden. Der Client wartet höchstens 120 Sekunden auf Antwort; ein ausgelasteter Dienst, Timeout, ungültiges JSON, erfundene Quellenbelege oder abgeschnittene Antworten erzeugen einen Hinweis. Notizen bleiben erhalten. Ein abgebrochener Browseraufruf kann serverseitig noch kurz weiterlaufen; Ergebnis nach Neuladen prüfen statt mehrfach klicken.

Der Status **Modell installiert** bestätigt Erreichbarkeit und Vorhandensein, keine Geschwindigkeit oder inhaltliche Qualität. Vor produktiver Nutzung Beispieltest und echte fachliche Prüfung durchführen. RAM-Bedarf und Geschwindigkeit hängen von CPU und Kontext ab. Home Assistant darf durch die Analyse nicht unbedienbar werden.

## Grenzen

Die lokale Textanalyse verwendet keine Websuche. Die Firmensuche unter **Kunden** bleibt bei der bisherigen getrennten OpenAI-Websuche. Preise, Rabatte, Steuer, Lager und Buchungen sind weiterhin feste Programmfunktionen. Es gibt keine automatischen Kundenanlagen, Bestellungen oder Versendungen durch das Modell. Ein lokales Modell ersetzt auch nicht die separat abgerechnete Entwicklungsarbeit in Codex.
