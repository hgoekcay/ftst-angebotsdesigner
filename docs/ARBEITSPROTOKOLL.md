# FTST Arbeitsprotokoll

Stand 07.10.2026. Dieses Protokoll ersetzt veraltete Versionsangaben in den Übergabedateien vom September.

## Abgeschlossen und auf Home Assistant geprüft

- 0.24.4: Eindeutige Ajax-Rückantworten und Kundenergänzungen übernehmen; durchgängiger Test bis zur Kalkulation und PDF.
- 0.24.5: Versandstatus mit Empfänger und Zeitpunkt. Mailserverannahme bleibt von bestätigter Zustellung getrennt.
- 0.24.6: Standard-Verkaufspreis aus Billomat, kein Sonderrabatt, 19 % Umsatzsteuer; bestehende Entwürfe werden erst nach Bearbeitung umgestellt. Alarmbogen auf beiden Seiten richtig bezeichnet.
- 0.24.7: Geänderte Empfängeradresse, Betreff und Nachricht werden vom Versandbereich zur E-Mail-Prüfung übergeben. PR 42 integriert (b65d0ac706da66d76b8f614066821b8cdb86bef2). Zehn CI-Prüfungen erfolgreich. Backup c45cb3bd vor Installation. Live-Test mit pruefung@example.com erfolgreich; keine Testmail gesendet und keine Billomat-Stammdaten geändert.
- Türsprechanlagenbogen: zwei A4-Seiten, 57 interaktive Felder; Layout und Feldstruktur geprüft. Google Drive: https://drive.google.com/file/d/1U6DsbUExijAxFDKRrgbhDRkBxTeB6x3P/view

## Weitere abgeschlossene Schritte

- 0.24.8: Alle fünf ausfüllbaren Aufnahmebögen direkt in der App. PR 43, zehn CI-Prüfungen erfolgreich, Backup 1a271ef7; Installation und PDF-Zugriff geprüft.
- 0.24.9: Entwürfe standardmäßig ausgeblendet, über Statusfilter weiterhin erreichbar. Kein Löschen von Billomat-Daten. PR 44, zehn CI-Prüfungen erfolgreich, Backup 189a1602; Installation und beide Filteransichten geprüft.

## Abgeschlossen: 0.25.0

Strukturierte Aufnahme für Alarm, Video, Zutritt, Schließzylinder und Türsprechanlagen. Die gespeicherte Systemwahl steuert Hinweise, Rückfragen, Schnellbausteine und PDF-Link. Ein Wechsel erfordert Speichern und erneute Prüfung; vorhandene Komponenten bleiben erhalten. Ajax bleibt Alarmstandard; andere Hersteller und genaue Modelle werden ausdrücklich ausgewählt. Explizite Dahua-Bezeichnungen und Montageleistungen erhalten keinen falschen Ajax-Präfix.

PR 45 integriert, 920 Tests und zehn CI-Prüfungen bestanden; Backup 100ee9fe, Version 0.25.0 installiert. Live-Test der Türsprechanlagenaufnahme bis zur lokalen Kalkulation erfolgreich.

## Nächste fachliche Grenze

Artikel und Preise kommen aus dem tatsächlichen Billomat-Katalog. Die Systemauswahl ersetzt keine technische Auslegung oder Modellprüfung. Ab 0.26.0 werden digital ausgefüllte FTST-Bögen ausgelesen; Scans bleiben Fotoeingaben. Eine genaue Standardserie für Zutritt, Türsprechanlagen und Schließzylinder ist noch nicht festgelegt.
## Arbeitsregeln

Keine Kundenkommunikation oder echte Billomat-Anlage zu Testzwecken. Veröffentlichung und Home-Assistant-Installation sind autorisiert, jeweils nach passenden Prüfungen und Sicherung. Keine automatischen verbindlichen Zusagen oder erfundenen technischen Varianten.

## Abgeschlossen: 0.26.0

PDF-Import der fünf digitalen FTST-Bögen: bekannte Formularstruktur, Systemerkennung, Mengen von Seite 1, Details beider Seiten als Notizen. Nullmengen entfallen, unklare Mengen bleiben offen. Ersetzt nach ausdrücklicher Wahl nur die Aufnahme; bestätigte Projektübernahme und Artikel-/Kundenauswahl bleiben separate Schritte. Verarbeitung in zeitbegrenztem Unterprozess. Tests, Sicherung, Veröffentlichung und Live-Prüfung werden im Statusprotokoll festgehalten.

PR 46 integriert, 931 Tests und zehn CI-Prüfungen bestanden; Backup f4112c11. Version 0.26.0 installiert und digital ausgefüllter Testbogen bis zur lokalen Kalkulation geprüft.

## Abgeschlossen: 0.26.1

Standardrückfragen anhand aktueller Angaben bereinigen, freie Fragen erhalten und bei gelöschten Angaben Standardfragen erneut öffnen. Alle fünf Systemarten, alte Aufnahmen und Projektübernahme berücksichtigt. 938 Tests erfolgreich. Veröffentlichung und Installation nach Sicherung; Abschluss im Statusprotokoll.

PR 47 integriert, zehn CI-Prüfungen bestanden; Backup 5c461781. Version 0.26.1 installiert und Fragebereinigung/Wiederöffnung live im Testprojekt geprüft.

## Aktueller Schritt: 0.26.2

Artikelsuche: PDF-Bezeichnung Tür-/Fensterkontakt der Ajax-Kontaktfamilie zuordnen. Herstellername Dahua allein darf keine beliebigen Treffer liefern; ausdrücklich abweichende Ajax-/Dahua-Hersteller ausschließen. Keine automatische Modellwahl. Veröffentlichung, Sicherung und Live-Prüfung im separaten Statusprotokoll.

