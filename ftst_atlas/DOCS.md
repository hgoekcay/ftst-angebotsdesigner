# Einrichtung und Abnahme

## Installation

1. Home-Assistant-Sicherung erstellen. FTST Lokale KI muss bereits laufen und
   `qwen3:4b-instruct-2507-q4_K_M` bereitstellen (etwa 2,5 GB).
   In der ATLAS-Konfiguration diesen exakten Modellnamen auswählen.
   Der unspezifische Alias `qwen3:4b` kann auf eine Thinking-Variante zeigen.
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
Ports und kein Zugriff auf HA-Konfigurationsdateien. Modellanfragen gehen ausschließlich an den eingestellten Ollama-Dienst.
Bei ausdrücklich aktiviertem Telegram werden Nachrichten über api.telegram.org übertragen. Die Installation des Container-Images
benötigt Internet; Chat-Inhalte gehen an den konfigurierten Modellserver.

Eine Generierung gleichzeitig, 4096 Token Kontext, maximal 384 neue Tokens,
vier CPU-Threads und kurze Modellhaltezeit. Dies begrenzt den Modellaufruf,
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

## Telegram (ab 0.2.0)

Telegram ist optional und standardmäßig ausgeschaltet. Nachrichten und Antworten
laufen über Telegram, auch wenn das Sprachmodell lokal bleibt. Bot-Chats sind
keine Ende-zu-Ende-verschlüsselten Secret Chats. Keine Zugangsdaten senden.

1. Beim offiziellen @BotFather mit /newbot einen eigenen Bot erstellen.
2. Den Token ausschließlich in HA → Apps → FTST ATLAS → Konfiguration im Feld
   telegram_token eintragen. Niemals in Chat, Screenshots, GitHub oder Protokolle.
3. In ATLAS → Wissen das Profil speichern; unter System die HA-Benutzer-ID
   ablesen und als telegram_ha_user_id eintragen. Damit bleibt die Wissenszuordnung
   ausdrücklich festgelegt; es gibt keine automatische Besitzerübernahme.
4. telegram_enabled einschalten. Die persönliche Telegram-ID wird als
   telegram_user_id eingetragen. Nur freigegebene private Chats dürfen KI und
   Firmenwissen verwenden. Für die ID-Ermittlung telegram_user_id zunächst leer lassen, starten und dem eigenen Bot /id schicken. Er zeigt nur die eigene Nummern-ID. Diese in telegram_user_id speichern und neu starten; erst danach sind Fragen und Firmenwissen freigegeben.
5. Speichern, App neu starten und zuerst /help, anschließend eine kurze Frage testen.

Long Polling braucht keine Portfreigabe und keinen öffentlichen Webhook. Nur eine
Instanz pro Bot betreiben. Vorhandene Webhooks werden nicht automatisch gelöscht.
Bei Anbieterfehlern wird gewartet; Token und Nachrichten werden nicht protokolliert.
Die Zustellung einer Antwort ist bei Netzwerkfehlern nicht garantiert. Es gibt
keinen automatischen Versand an Kunden und keine Telefonie/Sprachnachrichten.


## E-Mail-Assistenz ab 0.3.0

Der Bereich **E-Mails** verwendet ausschließlich den bestehenden internen Lesedienst von FTST STRATO Mail. Kein SMTP, Versand, Löschen, Verschieben, Markieren als gelesen oder Speichern von Entwürfen im Postfach. E-Mail-Inhalte werden nicht in Telegram oder in den allgemeinen Chat übernommen.

Einrichtung in der ATLAS-Konfiguration:

- `mail_enabled`: zunächst aus; erst nach bewusster Freigabe einschalten.
- `mail_bridge_url`: `http://76b650ab-ftst-strato-mail:8098` (alternativ lokale Installation `http://local-ftst-strato-mail:8098`). Kein öffentlicher Endpunkt.
- `mail_bridge_token`: vorhandener Verbindungsschlüssel der STRATO-Mail-App; ausschließlich im maskierten Konfigurationsfeld, niemals im Chat oder Firmenwissen eintragen.
- `mail_ha_user_id`: HA-Benutzer-ID aus ATLAS → System. Nur dieser Benutzer darf lesen und Entwürfe erstellen.
- `mail_account_id`: explizite Postfach-ID der Mail-App, standardmäßig `primary`.

Speichern und ATLAS neu starten. Danach E-Mails → Zeitraum wählen → E-Mails abrufen. Das Postfach bleibt unverändert. Die Vorschau umfasst höchstens 10 Nachrichten, älteste zuerst, nicht nur ungelesene Nachrichten. Bei mehr Treffern wird die Unvollständigkeit angezeigt; diese erste Ausbaustufe unterstützt keine Folgeseiten. Postfachordner und UIDVALIDITY werden bei jedem Abruf geprüft.

Nachrichten werden ausschließlich als Text dargestellt; externe Bilder/Links werden nicht geladen. Anhänge werden nicht ausgewertet. Bis zu 12.000 Zeichen werden angezeigt, höchstens 4.500 Textzeichen und begrenzte Kopfzeilen an das lokale Modell übergeben. Gekürzte Inhalte sind gekennzeichnet. Die KI erhält keine gespeicherten Firmengeheimnisse oder Notizen und hat keine ausführbaren Werkzeuge. Mailinhalte sind unvertrauenswürdige Daten; Entwürfe und Zusammenfassungen müssen geprüft werden.

Die Vorschau wird nicht dauerhaft gespeichert. Ein neuer Abruf ersetzt sie, ein Neustart entfernt sie. Auswahl-IDs gelten höchstens 30 Minuten. Entwürfe stehen nur auf der geöffneten Seite und gehen beim Neuladen verloren. Kein automatisches Lernen aus eingehenden Nachrichten.

Abnahme: mit dem freigegebenen Benutzer eine bekannte E-Mail abrufen, Quelle/Text prüfen und einen Entwurf erzeugen. Danach sicherstellen, dass ein anderer HA-Benutzer keinen Zugriff erhält und die Originalmail unverändert bleibt. Live-Abnahme ist erst nach Einrichtung des Verbindungsschlüssels möglich.
