# FTST Arbeitsprotokoll

Stand 07.10.2026. Dieses Protokoll ersetzt veraltete Versionsangaben in den Übergabedateien vom September.

## Abgeschlossen und auf Home Assistant geprüft

- 0.24.4: Eindeutige Ajax-Rückantworten und Kundenergänzungen übernehmen; durchgängiger Test bis zur Kalkulation und PDF.
- 0.24.5: Versandstatus mit Empfänger und Zeitpunkt. Mailserverannahme bleibt von bestätigter Zustellung getrennt.
- 0.24.6: Standard-Verkaufspreis aus Billomat, kein Sonderrabatt, 19 % Umsatzsteuer; bestehende Entwürfe werden erst nach Bearbeitung umgestellt. Alarmbogen auf beiden Seiten richtig bezeichnet.
- 0.24.7: Geänderte Empfängeradresse, Betreff und Nachricht werden vom Versandbereich zur E-Mail-Prüfung übergeben. PR 42 integriert (b65d0ac706da66d76b8f614066821b8cdb86bef2). Zehn CI-Prüfungen erfolgreich. Backup c45cb3bd vor Installation. Live-Test mit pruefung@example.com erfolgreich; keine Testmail gesendet und keine Billomat-Stammdaten geändert.
- Türsprechanlagenbogen: zwei A4-Seiten, 57 interaktive Felder; Layout und Feldstruktur geprüft. Google Drive: https://drive.google.com/file/d/1U6DsbUExijAxFDKRrgbhDRkBxTeB6x3P/view

## Aktueller Schritt: 0.24.8

Alle fünf vorhandenen Bögen direkt in der App bereitstellen. Die Vorlagenseite verändert keine Kunden, Angebote oder Kalkulationen. Stand der Veröffentlichung und Installation nach Abschluss ergänzen.

## Nächste fachliche Grenze

Die strukturierte Technikeraufnahme und ihre Rückfragen sind weiterhin auf Ajax-Alarmanlagen ausgelegt. Vor einer Erweiterung für Video, Zutritt und Türsprechanlagen muss die herstellerspezifische Zuordnung festgelegt werden. Die Formulare selbst sind herstellerneutral; Artikel und Preise dürfen nur aus dem tatsächlichen Billomat-Katalog kommen.

Danach: Aufnahme je Systemtyp, Prüfung von Pflichtangaben, manuelle Artikelwahl, Kalkulation und Montageübersicht durchgängig verbinden. Ausgefüllte PDF-Dateien werden noch nicht automatisch importiert. Fotos und Text bleiben die bestehenden Eingänge.

## Arbeitsregeln

Keine Kundenkommunikation oder echte Billomat-Anlage zu Testzwecken. Veröffentlichung und Home-Assistant-Installation sind autorisiert, jeweils nach passenden Prüfungen und Sicherung. Keine automatischen verbindlichen Zusagen oder erfundenen technischen Varianten.

