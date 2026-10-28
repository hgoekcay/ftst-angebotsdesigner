# ATLAS · FT Sicherheitstechnik

Lokaler Assistent für Fragen, Arbeitsvorbereitung, Firmenwissen und Aufgaben.
Verwendet die bereits installierte **FTST Lokale KI** als Modellserver.
Ab 0.2.4 ist für direkte Antworten `qwen3:4b-instruct-2507-q4_K_M` vorgesehen
(einmaliger Download etwa 2,5 GB). Online-Beratung ist ab 0.4.0 optional und ausdrücklich konfigurierbar.

- Chat mit Firmenprofil und ausdrücklich gespeicherten Erinnerungen.
- Wissen mit Quellenangabe, einsehbar und löschbar.
- Aufgaben erfassen und abhaken.
- Bedienung über Home Assistant, auch am Handy.
- Optionaler privater Telegram-Chat mit ausdrücklicher Kontofreigabe.

**Diese Version ist ein Pilot.** WhatsApp, Telefonanrufe, Gerätesteuerung und E-Mail-Versand
sind noch nicht angebunden. Billomat wird ab 0.5.0 ausschließlich lesend für die
Belegvorbereitung angebunden; regelmäßiger Import und Telegram-Berichte sind optional.
ATLAS führt keine Geräte- oder Shellbefehle aus. Antworten sind Entwürfe und
müssen fachlich geprüft werden. Die Oberfläche zeigt fehlende Anbindungen offen.

„Lernen“ bedeutet hier: vom Nutzer gespeichertes Wissen wird bei passenden
Fragen wieder eingeblendet. Das Sprachmodell wird nicht nachtrainiert.

Einrichtung, Grenzen und Abnahme stehen im Reiter **Dokumentation**.

Ab Version 0.3.0 gibt es zusätzlich einen optionalen Bereich **E-Mails**: lesende STRATO-Vorschau sowie lokale Zusammenfassungen und Antwortentwürfe. Standardmäßig deaktiviert, nur für einen ausdrücklich zugeordneten Home-Assistant-Benutzer. Kein Versand und keine automatische Wissensübernahme. Einrichtung und Grenzen stehen in der Dokumentation.

Ab 0.4.0: optionale OpenAI-Beratung mit Websuche, Quellen und Tageslimit sowie dauerhafte Hintergrundaufträge für ausdrücklich gestartete Anfragen. Ein eigener API-Zugang ist erforderlich. „Nur lokal“ bleibt verfügbar. Keine automatische Übernahme der privaten ChatGPT-Gesprächshistorie.


Ab 0.5.0: Belegvorbereitung aus freigegebenen STRATO-Postfächern und Billomat, prüfbare Monatsausgabe, Telegram-OP-/Beleglisten und getrennte mobile Mitarbeiter-Uploads. Neue Zugänge werden gesondert konfiguriert; Einrichtung und Grenzen siehe DOCS.md.
