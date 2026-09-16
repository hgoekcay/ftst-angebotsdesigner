# Mail-Arbeitsliste 0.8.0

Auf der Startseite unter Antwortassistent. Manuelle Textaufnahme oder eine EML-Datei bis 8 MiB. Kein IMAP, SMTP, OCR oder automatischer Buchhaltungsexport.

## Bedienung und Grenzen

- Mehrere Kategorien pro Nachricht: Kundenanfrage, Service/Störung, Laufender Auftrag (einschließlich Termine), Rechnung/Gutschrift, Einkauf/Lieferung, Allgemein. Der lokale Modellvorschlag wird erst per Übernahme angewendet. Kategorien und Bearbeitung bleiben manuell korrigierbar.
- Bearbeitung, Verantwortlicher, Wiedervorlage, Projektbezug als Freitext und Vermerk. Warten braucht Wiedervorlage und Vermerk; Erledigt einen Vermerk zur tatsächlichen Handlung. Keine Versandbehauptung durch einen Antwortentwurf.
- Belegart, Originalbezug und Angaben werden manuell geprüft. Belegstatus ist von Bearbeitung und Zahlung getrennt. Export/Übergabe/Buchung/Zahlung benötigen eine ausdrückliche Bestätigung mit Vermerk. Geänderte Belegangaben benötigen erneute Bestätigung. Ein Download ändert keinen Status.
- Original-EML und dekodierte Anhangbytes werden gemeinsam mit dem Arbeitsvorgang in SQLite gespeichert. Erneuter Import identischer Originalbytes öffnet den bestehenden Vorgang, ohne Bearbeitung zu überschreiben. Identische Anhänge in unterschiedlichen Mails werden angezeigt; beide Mails bleiben erhalten. Semantische Rechnungsduplikate werden noch nicht automatisch erkannt.
- Höchstens 100 MIME-Teile/20 Ebenen; Originale bleiben unverändert. HTML wird nicht gerendert, externe Bilder nicht nachgeladen. Alle Anhänge, auch PDF/Bilder/HTML, sind sichtbar **nicht ausgewertet**. Downloads nur als Datei mit nosniff/Sandbox. Das ist kein Virenscanner; keine Datei wird automatisch geöffnet oder ausgeführt.
- Nur Klartext bis 4000 Zeichen gelangt in die lokale Analyse. Längere Nachrichten werden nicht automatisch gekürzt: das Prüffeld bleibt leer, vollständiger Text ist herunterladbar, ein Ausschnitt kann manuell eingefügt werden. Die Oberfläche nennt Feldlänge und gesamte Klartextlänge. Die Ergebnisse beziehen sich nur auf das gespeicherte Prüffeld.
- Ungespeicherte Änderungen sperren andere Bearbeitungsabschnitte bis zum Speichern. Server prüft zusätzlich die Revision; parallele Änderungen werden nicht überschrieben.

Schema 3 ergänzt mail_blobs. Bestehende Daten werden übernommen. Rückkehr zu 0.7.0 benötigt die zugehörige Sicherung von vor dem Update, weil diese Version Schema 3 bewusst ablehnt. Keine Aussage zu gesetzeskonformer Archivierung.

## Späterer geschützter IMAP-Zugang

Der geprüfte Eingabeweg ist Home Assistant → Apps → FTST AngebotsDesigner → Konfiguration: dort später native Passwortoption, keine FTST-Webmaske und kein Passwort im Chat. In 0.8.0 gibt es dieses Feld bewusst noch nicht, weil es noch keinen abrufenden IMAP-Dienst gibt. Vor diesem Ausbau keine Zugangsdaten anfordern.

Produktiv setzt run.sh FTST_REQUIRE_INGRESS=1. Flask akzeptiert dann nur den tatsächlichen Socket-Peer 172.30.32.2; Forwarding-Header reichen nicht. Keine Hostports/Hostnetz. Lokale Entwicklung läuft explizit außerhalb des HA-Startskripts. panel_admin allein ist kein Rollencheck. Quelle: https://developers.home-assistant.io/docs/apps/presentation/#ingress

Ein späteres password-Feld maskiert die Oberfläche, garantiert jedoch keine verschlüsselte Speicherung: HA übergibt Optionen als /data/options.json und nimmt Optionen auch in Supervisor-Backupmetadaten auf. Passwort dann gezielt serverseitig lesen, nie in Datensätze, Prompts, Exporte, UI oder FTST-Protokolle kopieren. Plattformadministratoren und entschlüsselte Backups bleiben ein Zugriffsweg. Verschlüsselung des verwendeten Backupziels vor echten Zugangsdaten prüfen; HA-Downloads können entschlüsselt sein. Quellen: https://developers.home-assistant.io/docs/apps/configuration/ und https://www.home-assistant.io/common-tasks/general/#downloading-your-local-backups

IMAP-Plan: imap.strato.de:993, vollständige Mailadresse, verifiziertes TLS; SELECT readonly / BODY.PEEK, begrenzter Pilot ab Aktivierung (optional bestätigte 30 Tage), UIDVALIDITY/UID plus Originalhash, keine Seen-Markierung und kein Verschieben/Löschen. Noch nicht implementiert. STRATO: https://www.strato.de/faq/mail/e-mailserver-adressen-ports-ssl-tls/

## Anschließend gewünschte Buchhaltungsvorbereitung

Billomat ist laut Nutzer bereits mit der Bank verbunden und soll führendes System für Eingangsbelege und Bankabgleich bleiben. Kein separates Bankimportsystem und keine neuen Bankzugänge. Zuerst vorhandene Billomat-Funktionen und API-Rechte lesend prüfen: Eingangsbelege, Originalupload, Dubletten, Zahlungsrückmeldungen. Die Banking-Produktfunktion allein belegt keinen Banktransaktions-API-Zugriff. Danach E-Mail-Beleg → geprüfte Billomat-Erfassung/Zuordnung → vorhandener Bankabgleich → Monats-Paketvorschau mit Originalen und offenen Fällen. Die manuellen Belegangaben dieser Pilotstufe sind Prüfnotizen, keine zweite Buchhaltung.

Bankabgleich ist keine steuerliche Buchung. Steuerbüro-Empfänger und Übergabeweg sind offen. Eine echte Sendung braucht den konkret geprüften Empfänger, Zugang und Freigabe genau des angezeigten Pakets. Kein solcher Versand oder Bankzugriff ist Bestandteil von 0.8.0. Quellen zur anschließenden Prüfung: https://www.billomat.com/api/eingangsrechnungen/ und https://www.billomat.com/add-ons/billomat-banking/
