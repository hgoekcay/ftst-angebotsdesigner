## 0.4.0

- Neue Apple-inspirierte Oberfläche mit Systemschrift, adaptivem Hell-/Dunkelmodus und mobiler Navigation.

- Optionale OpenAI-Beratung mit Websuche und anklickbaren Quellen. Keine Verbindung zu einem privaten ChatGPT-Chat.
- Automatischer Modus für Recherchebegriffe und lokale Modellfehler; „Nur lokal“ verhindert Online-Anfragen.
- Hintergrundaufträge bleiben beim Schließen der Oberfläche aktiv. Ergebnisse sind bis zu sieben Tage unter Aufgaben abrufbar.
- Begrenzte Online-Anfragen pro UTC-Tag, keine automatische Wiederholung unsicher abgeschlossener API-Aufrufe.
- Online-Kontext standardmäßig nur die aktuelle Frage; Firmenprofil separat zuschaltbar. Postfach, Erinnerungen und Chatverlauf werden nicht automatisch übertragen.
- Telegram: /online FRAGE, /lokal FRAGE und automatische Auswahl.

## 0.3.0

- Neuer Bereich E-Mails mit lesender STRATO-Vorschau für einen explizit freigegebenen HA-Benutzer.
- Bis zu 10 Nachrichten im gewählten Zeitraum, älteste zuerst; unvollständige Vorschauen und gekürzte Texte sind gekennzeichnet.
- Lokale Zusammenfassungen und Antwortentwürfe, ohne Versand, Mailboxänderungen oder automatisches Speichern ins Firmenwissen.
- Postfachzugriff standardmäßig aus. Vorschau bleibt nur im Arbeitsspeicher; Auswahl-IDs nach 30 Minuten, neuem Abruf oder Neustart ungültig.
- E-Mail-Auswertung erhält keine privaten Firmenprofile oder gespeicherten Notizen; Roh-HTML und externe Bilder werden nicht geladen.

# 0.2.4

- Explizite Qwen3-4B-Instruct-2507-Q4_K_M-Variante für direkte Antworten unterstützen.
- Instruct ohne Denk-Prefill ansteuern; vier CPU-Threads und 384 Antworttokens.
- Vorhandenes Modell bleibt erhalten; Instruct-Modell muss lokal vorbereitet sein.

# 0.2.3

- Aufeinanderfolgende Telegram-Nachrichten nicht mehr durch Zehn-Sekunden-Sperre verwerfen.
- Aufgaben auch mit tasks oder Aufgaben abrufen; KI-Fragen sofort bestätigen.
- Antwortbudget auf 768 Tokens erhöhen, unvollständige Antworten weiterhin abweisen.

# 0.2.2

- Abgeschlossene Modellantworten von separaten oder vorangestellten Denk-Ausgaben trennen.
- Leere, unvollständige oder weiterhin markierte Antworten bleiben gesperrt.

# 0.2.1

- Telegram-Felder optional: ID-Ermittlung lässt sich ohne Telegram-Nutzer-ID speichern.
- Verbindungsstatus im Protokoll ohne Token oder Nachrichteninhalte.

# 0.2.0

- Optionale Telegram-Textanbindung per Long Polling, standardmäßig deaktiviert.
- Explizite Zuordnung privater Telegram-ID zum gespeicherten HA-Profil.
- /id ohne Wissenszugriff; /tasks und /remember für freigegebenen Nutzer.
- Qwen-Korrektur aus 0.1.1 enthalten, Live-Abnahme weiterhin erforderlich.

# 0.1.0

- Erste separate ATLAS-App für vorhandenes lokales Ollama.
- Mobile deutsche Oberfläche mit Chat, Wissen, Aufgaben und Systemstatus.
- Explizites, einsehbares Gedächtnis statt ungeprüfter automatischer Übernahme.
- Keine externen Aktionen; fehlende Kommunikationskanäle klar gekennzeichnet.
