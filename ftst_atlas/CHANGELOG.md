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
