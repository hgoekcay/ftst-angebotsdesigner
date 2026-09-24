# Angebot per E-Mail oder WhatsApp übergeben

Ab 0.20.0 steht bei einem freigegebenen Billomat-Angebot unter dem Angebotskopf „Angebot versenden“. Lokale und Billomat-Entwürfe bleiben interne Prüfdokumente.

1. E-Mail beziehungsweise Mobil-/Telefonnummer des Kunden prüfen. Diese Felder stammen aus Billomat. Änderungen gelten nur für diesen Versand und werden nicht in Billomat gespeichert.
2. Betreff und Nachricht bei Bedarf anpassen; „Per E-Mail versenden“ oder „Per WhatsApp versenden“ wählen.
3. Die App ruft die aktuelle gestaltete PDF mit der bestehenden Home-Assistant-Anmeldung ab.
4. PDF speichern, anschließend die E-Mail oder den WhatsApp-Chat über den angebotenen Link öffnen, die PDF anhängen und dort senden.
5. Auf unterstützten Handys alternativ „PDF direkt an eine App teilen“ wählen. Im nativen Teilen-Menü werden App und Empfänger selbst gewählt; der Browser kann diese nicht vorgeben.

Der Empfängerlink übernimmt Kontaktdaten und Nachricht, aber keine Datei. Ein mailto-Link kann keinen PDF-Anhang übertragen; WhatsApp Click-to-Chat ebenfalls nicht. Die App behauptet deshalb keinen erfolgreichen Versand. Natives Teilen bestätigt nur eine Übergabe an eine App, keine Zustellung.

Für serverseitigen Direktversand sind gesonderte sendefähige Postfach- bzw. WhatsApp-Business-Anbindungen erforderlich. Die vorhandene Mail-Bridge ist ausschließlich lesend. Es werden keine Home-Assistant-Ingress-Links an Kunden weitergegeben und keine PDFs öffentlich bereitgestellt.

Deutsche Ortsvorwahlen mit führender 0 werden nach +49 normalisiert. Ausländische Nummern mit + oder 00 und Landesvorwahl eingeben. Ob eine Nummer tatsächlich WhatsApp nutzt, lässt sich vor dem Öffnen nicht feststellen.

Technische Grundlagen: [WhatsApp Click-to-Chat](https://faq.whatsapp.com/5913398998672934), [Web Share API](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/share).
