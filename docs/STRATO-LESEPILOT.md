# STRATO-Lesepilot – lokaler Entwicklungsstand, 19.09.2026

Implementiert auf `codex/strato-readonly-local`, aufbauend auf dem unveränderten lokalen Angebotsstand 0.11.0. Noch nicht veröffentlicht oder installiert. Die Versionsanzeige 0.11.0 ist keine neue Releasefreigabe.

## Bedienung nach einer separat freigegebenen Installation

1. Vor Installation Sicherung erstellen und Wiederherstellbarkeit prüfen. Sicherungen mit Zugangsdaten verschlüsseln.
2. In Home Assistant unter Einstellungen → Apps → FTST AngebotsDesigner → Konfiguration den STRATO-Lesepiloten aktivieren und das Passwort von info@ftst.eu im Passwortfeld eingeben. Speichern und App neu starten. Passwort weder im Chat noch in der Mail-Arbeitsliste eingeben.
3. Mail-Arbeitsliste → STRATO-Eingang → Startpunkt ab jetzt festlegen. Dies bestätigt die Verbindung und speichert UIDVALIDITY/UIDNEXT; vorhandene Nachrichten werden nicht übernommen.
4. Jetzt bis zu 10 neue E-Mails lesen. Neue Nachrichten erscheinen als Vorgänge in der bestehenden Arbeitsliste. Weitere Abrufe werden bewusst per Klick gestartet.

Der Schalter ist standardmäßig aus. Das Passwortfeld ist verdeckt, aber die HA-Konfigurationsdatei selbst dadurch nicht verschlüsselt. Nur vertrauenswürdige Administratoren dürfen App-Konfiguration und Backups lesen. Keine zusätzlichen veröffentlichten Ports oder neuen HA-Berechtigungen vorgesehen.

## Verhalten und Grenzen

- Fester Server imap.strato.de:993, TLS mit Zertifikats- und Hostnamenprüfung, Konto info@ftst.eu, ausschließlich INBOX.
- SELECT schreibgeschützt, Inhalte über BODY.PEEK. Kein Versand, Löschen, Verschieben, Setzen von Gelesen-Markierungen, CLOSE oder EXPUNGE.
- Höchstens zehn Nachrichten, 8 MiB je Nachricht, 20 MiB pro Abruf. Netzwerkantworten zusätzlich begrenzt. Socket-Zeitlimit 15 Sekunden und Laufzeitprüfungen gegen 120 Sekunden; kein garantiert sekundengenauer Abbruch jeder Systemoperation.
- Original-EML und Anhänge bleiben lokal erhalten. Keine automatische KI-Auswertung, OCR, HTML-Auswertung oder Billomat-Übertragung.
- Identität aus Postfach, Ordner, UIDVALIDITY und UID; zusätzlich Original-Hash gegen doppelte Vorgänge. Bestehende manuelle Bearbeitung bleibt erhalten.
- Alle Nachrichten eines Abrufs werden vor dem Speichern geprüft. Originale, Zuordnungen und Abrufstand werden in einer SQLite-Transaktion übernommen. Fehler lassen den Abrufstand unverändert; Wiederholung ist möglich.
- Bei geänderter UIDVALIDITY wird angehalten. Technischer Abgleich erforderlich; der Pilot bietet keinen automatischen Reset. Übergroße oder unlesbare Nachrichten werden nicht still übersprungen und können den Fortschritt blockieren.
- Kein rückwirkender 30-Tage-Import, kein Zeitplan und kein Hintergrunddienst in dieser Stufe.

## Prüfung

Am 19.09.2026: 84 Tests bestanden (Strato-Transport, Strato-Oberfläche, bestehender Mailworkflow, Antwortassistent und Persistenz). Ausschließlich Mocktransport, keine echte STRATO-Verbindung oder echten Zugangsdaten. Kritische Ruff-Prüfungen bestanden.

Lokaler Browser: Startpunkt gesetzt, eine fiktive Nachricht importiert, Folgeabruf ohne weiteren Vorgang und genau ein Eintrag in der Arbeitsliste bestätigt. STRATO-Seite bei 320/390 Pixeln ohne horizontalen Dokumentüberlauf (305/305 bzw. 375/375 mit Scrollbar). Arbeitsliste bei 320 Pixeln ebenfalls 305/305. Kein Ersatz für den späteren Test im tatsächlichen Home-Assistant-Ingress auf dem Handy.

## Noch offen vor Echtbetrieb

Separat freigegebene Veröffentlichung und Installation mit Sicherung; danach Passwort direkt durch den Administrator in HA hinterlegen. Anschließend echten Verbindungsaufbau, Startpunkt, Eingang einer kontrollierten Testmail und unveränderte Gelesen-Markierung prüfen. Kein Passwort für die weitere lokale Entwicklung erforderlich.

## Technische Referenzen

- https://www.strato.de/faq/mail/e-mailserver-adressen-ports-ssl-tls/
- https://docs.python.org/3.13/library/imaplib.html
- https://developers.home-assistant.io/docs/apps/configuration/
