# Änderungen

## 0.1.19

- Kundendarstellung dauerhaft in SQLite, getrennt nach Billomat-Konto und Angebot.
- Editor, Vorschau und PDF verwenden denselben gespeicherten Stand.
- Noch gültige alte Session-Daten werden einmalig übernommen; neuere Datenbankstände haben Vorrang.
- Unlesbare Datenbanken werden nicht ersetzt; Speicherfehler liefern keinen Erfolgshinweis.
- BWA als eigenständiges Kürzel und CO-Melder werden erkannt; ungültige/alte Systemtypen abgefangen.
- Gemischte Gewerke als Kombination; automatische Erkennung im Editor wieder auswählbar.
- PDF öffnet in eigenem Tab. Bestehende FTST-Gestaltung erhalten.
- Automatisierte Tests und Abnahmeprotokoll ergänzt.
