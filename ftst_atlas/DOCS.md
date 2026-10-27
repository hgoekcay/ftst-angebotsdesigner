# Einrichtung und Abnahme

## Installation

1. Home-Assistant-Sicherung erstellen. FTST Lokale KI muss bereits laufen und
   `qwen3:4b` bereitstellen.
2. Apps-Store aktualisieren, **FTST ATLAS** installieren und starten.
3. **Weboberfläche öffnen**. Keine Ports freigeben, keine Routeränderung nötig.
4. Im Bereich Wissen das eigene Firmenprofil eintragen (maximal 2.000 Zeichen). Nur freigegebene Fakten
   speichern. Vertrauliche Angaben gehören ausschließlich in die laufende App,
   niemals in das öffentliche GitHub-Repository.
5. Eine kurze Frage stellen, beispielsweise „Welche Aufgaben kannst du übernehmen?“.

Die Standardadresse des bestehenden Modells ist
`http://76b650ab-ftst-local-ai:11434`. Diese Pilotversion erlaubt nur diesen lokalen Dienst und lokale Testadressen;
ein anderer Repository-Hostname benötigt eine geprüfte Codeanpassung. Zugang erfolgt über Home Assistants angemeldete Ingress-Sitzung.

## Abnahme auf dem Zielgerät

- Oberfläche am Desktop und Smartphone öffnen.
- Firmenprofil speichern und erneut laden; Inhalt prüfen.
- Erinnerung mit Quelle anlegen; danach passende Frage stellen.
- Erinnerung löschen und kontrollieren, dass sie nicht mehr angezeigt wird.
- Aufgabe anlegen, abhaken und nach App-Neustart erneut kontrollieren.
- Kurze deutsche Modellantwort abwarten, Laufzeit und Sinn prüfen.
- Bei nicht verfügbarem Modell muss ein verständlicher Fehler erscheinen.
- Home Assistant muss während einer Antwort weiter bedienbar bleiben.

## Datenschutz und Betrieb

Wissen und Aufgaben liegen in einer SQLite-Datei im persistenten `/data`-Ordner.
App-Sicherungen enthalten diese Daten; eine Deinstallation kann sie löschen.
Nutzerbezogene Inhalte dürfen nur über die eigene Home-Assistant-Sitzung
zugänglich sein. Das App-Panel ist für Administratoren vorgesehen.

Keine Supervisor-API, kein Docker-Socket, kein Hostnetzwerk, keine veröffentlichten
Ports und kein Zugriff auf HA-Konfigurationsdateien. Die App darf ausschließlich
den eingestellten Ollama-Dienst anfragen. Die Installation des Container-Images
benötigt Internet; Chat-Inhalte gehen an den konfigurierten Modellserver.

Eine Generierung gleichzeitig, 4096 Token Kontext, maximal 256 neue Tokens,
zwei CPU-Threads und kurze Modellhaltezeit. Dies begrenzt den Modellaufruf,
ist aber keine harte RAM-Quote. AngebotsDesigner und ATLAS teilen sich dieselbe
Modellressource. Umfangreiche Antworten können auf dem Mini-PC langsam sein.

## Funktionsgrenzen

- Keine echte WhatsApp-/Telefonie-Anbindung und kein automatischer Versand.
- Keine Türöffnung, Unscharfschaltung oder andere Gerätesteuerung.
- Kein automatischer Zugriff auf E-Mails, Billomat, Kalender oder Kundendateien.
- Kein nächtliches eigenständiges Weiterprogrammieren, kein Modelltraining.
- Keine Garantie für aktuelle Normen, Rechtsfragen oder fachliche Richtigkeit.
- Kein OpenJarvis-Laufzeitbestandteil in dieser Version.

Nächste Ausbaustufen: ausgewählte HA-Zustände lesend, freigegebene Dokumente,
offizielle WhatsApp-Anbindung mit Vorlagen und Antworten, Telefonie mit
Bestätigungen, erst danach einzeln freigegebene Aktionen. Jede Anbindung benötigt
einen eigenen Integrationstest und passende Zugriffsrechte.

## Lokaler Entwicklungstest

Vom Repository-Verzeichnis:

```sh
python3 -m unittest discover -s tests/atlas -v
ATLAS_DEV=1 ATLAS_DATA_DIR=/tmp/atlas-dev python3 ftst_atlas/app.py
```

Der Entwicklungsmodus darf ausschließlich lokal binden. Er ist nicht für eine
Netzwerkfreigabe gedacht. Für Home Assistant ausschließlich den normalen
Ingress-Modus verwenden.

## Gesprächskontext

Der Chat übergibt die letzten vier Gesprächsbeiträge mit jeweils höchstens 500 Zeichen.
Der sichtbare Verlauf bleibt nur während der geöffneten Seite erhalten. Dauerhaftes
Wissen muss ausdrücklich gespeichert werden. Pro Antwort werden ausgewählte
Wissensauszüge und offene Aufgaben in begrenztem Umfang berücksichtigt; dies ist
noch keine vollständige Dokumentensuche.
