# Leistungsvorschlag per E-Mail oder WhatsApp

Ab 0.21.0 heißen kundenseitige PDFs und Nachrichten „Leistungsvorschlag“. Die Billomat-Nummer bleibt erhalten. Lokale und Billomat-Entwürfe bleiben interne Prüfdokumente.

1. E-Mail beziehungsweise Mobil-/Telefonnummer des Kunden prüfen. Diese Felder stammen aus Billomat. Änderungen gelten nur für diesen Versand und werden nicht in Billomat gespeichert.
2. Betreff und die getrennten Texte prüfen: ausführliche E-Mail unter „E-Mail-Text prüfen und bearbeiten“, kurzer WhatsApp-Text darunter. „PDF für E-Mail vorbereiten“ oder „PDF für WhatsApp vorbereiten“ wählen.
3. Die App ruft die aktuelle gestaltete PDF mit der bestehenden Home-Assistant-Anmeldung ab.
4. Auf unterstützten Geräten die Hauptaktion **„PDF an WhatsApp teilen“** bzw. **„PDF an E-Mail-App teilen“** wählen. Im nativen Teilen-Menü werden App und Empfänger selbst gewählt; der Browser kann diese nicht vorgeben. Vor dem Senden den PDF-Anhang prüfen.
5. Manche Apps übernehmen beim Dateiteilen nur die PDF. Dann den passenden Text mit „Text kopieren“ ergänzen.
6. Ist Dateiteilen nicht möglich, PDF speichern und in WhatsApp über „+ / Büroklammer → Dokument“ bzw. in der E-Mail anhängen. Die eingeklappte Alternative „Empfänger direkt öffnen“ überträgt nur Text und Empfänger; sie ist ausdrücklich ohne PDF gekennzeichnet.

Der Empfängerlink übernimmt Kontaktdaten und Nachricht, aber keine Datei. Ein mailto-Link kann keinen PDF-Anhang übertragen; WhatsApp Click-to-Chat ebenfalls nicht. Die App behauptet deshalb keinen erfolgreichen Versand. Natives Teilen bestätigt nur eine Übergabe an eine App, keine Zustellung.

Für serverseitigen Direktversand sind gesonderte sendefähige Postfach- bzw. WhatsApp-Business-Anbindungen erforderlich. Die vorhandene Mail-Bridge ist ausschließlich lesend. Es werden keine Home-Assistant-Ingress-Links an Kunden weitergegeben und keine PDFs öffentlich bereitgestellt. Ein mailto-Link enthält weder HTML-Formatierung noch Referenzlogos; dafür ist eine gesonderte HTML-Mail-Anbindung nötig. Die bestehende Mailvorlage direkt in Billomat wird durch dieses Update nicht verändert.

Die E-Mail-Vorlage enthält die vom Nutzer gelieferte FTST-Signatur sowie einen Link zur telefonischen Erstberatung. Beide Texte sind vor Versand bearbeitbar und werden getrennt übergeben. Änderungen an Feldern verwerfen vorbereitete Versandaktionen.

Deutsche Ortsvorwahlen mit führender 0 werden nach +49 normalisiert. Ausländische Nummern mit + oder 00 und Landesvorwahl eingeben. Ob eine Nummer tatsächlich WhatsApp nutzt, lässt sich vor dem Öffnen nicht feststellen.

Technische Grundlagen: [WhatsApp Click-to-Chat](https://faq.whatsapp.com/5913398998672934), [Web Share API](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/share).
