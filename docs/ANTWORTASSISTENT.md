# Lokaler Antwortassistent ab 0.7.0

Auf der Startseite **Antwortassistent** öffnen, einen Namen und den Text einer Kundenanfrage eingeben und speichern. Maximal 4000 Zeichen, noch keine Anhänge oder Postfachanbindung. Die Anfrage bleibt mit dem bearbeiteten Antwortentwurf in der vorhandenen lokalen Datenbank erhalten.

**Gespeicherte Anfrage lokal auswerten** benutzt ausschließlich den vorhandenen Ollama-Dienst. Die KI wählt bis zu fünf wörtlich belegte Textausschnitte und fehlende Angaben aus einer festen Liste. Der Antworttext entsteht anschließend aus festen Textbausteinen. Kundenanweisungen und freie Modelltexte werden nicht in die Antwort übernommen. Es gibt weder Toolaufrufe noch Mailversand. Die Funktion eignet sich zunächst für technische Kundenanfragen; bei Verwaltungsanliegen kann der allgemeine Text unpassend sein.

Ergebnisse, Auszüge und Rückfragen vor Verwendung prüfen: Ein wörtliches Zitat ist keine Bestätigung des Inhalts. Auch fehlende Angaben können falsch eingeschätzt werden. Preise, technische Machbarkeit, Verfügbarkeit oder verbindliche Termine werden nicht zugesagt.

Die erste Analyse füllt ein leeres Antwortfeld. Bearbeitete Antworten bleiben bei weiteren Analysen erhalten. Ein abweichender KI-Vorschlag wird separat angezeigt und kann ausdrücklich übernommen werden. **Antwort kopieren** kopiert den aktuellen Feldinhalt; bei verweigerter Zwischenablage wird der Text zum manuellen Kopieren markiert. Änderungen separat speichern. Ungespeicherte Bearbeitungen sperren Analyse und Übernahme im Browser.

Unveränderte Eingaben verwenden das gespeicherte Ergebnis, sofern Modell und interne Promptversion unverändert sind. Bewusste Neuauswertung ist möglich. Derselbe globale lokale KI-Sperrmechanismus wie für Projekte verhindert gleichzeitige Modellaufrufe; identische Zeit-, Eingabe- und Ausgabelimits gelten. Lokale Fehler aktivieren keinen Cloud-Ersatz. Der gespeicherte Text und vorhandene Entwurf bleiben erhalten. Revisionsprüfung verhindert, dass eine langsame Analyse zwischenzeitliche Änderungen überschreibt.

Der Pilot hat keinen Postfachzugriff, EML-Import, automatische Sortierung, Belegworkflow oder Buchhaltungsanbindung. Er verändert keine Nachrichten in Strato/Outlook und versendet nichts. Diese Erweiterungen benötigen eine eigene geprüfte Import- und Statuslogik. Zugangsdaten gehören nicht in eingefügte Anfragetexte.
