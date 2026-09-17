# Barcodeentnahme im Hauptlager

## Ablauf

Unter **Lager → Für Auftrag scannen** einen bereits beauftragten, aktiven Auftrag auswählen. Barcode per Kamera, Hardware-Scanner oder Texteingabe erfassen. Die Erkennung wählt nur den Artikel; sie verändert weder Bestand noch Menge. Nach einem Treffer stoppt die Kamera. Für einen weiteren Scan bewusst erneut starten.

Artikel, Auftrag, Lagereinheit, Verpackungsinhalt und verfügbare Menge prüfen. Menge eingeben und **Entnahme bestätigen** drücken. Erst eine Serverbestätigung bedeutet, dass gebucht wurde. Die alte Auswahlkarte wird danach ausgeblendet, damit kein veralteter Verfügbarkeitswert neben dem neuen Bestand steht.

Die Verfügbarkeit schließt die eigene Auftragsreservierung ein. Fremde Reservierungen bleiben geschützt. Zusätzlich begrenzt der offene Auftragsbedarf die Entnahme. Ungezählte Artikel können nicht entnommen werden. Fahrzeuge, Umlagerungen und Seriennummernverwaltung sind nicht Bestandteil dieses Piloten.

## Einmalige Zuordnung

Unter **Barcodes zuordnen** einen vorhandenen Lagerartikel wählen und den tatsächlich aufgedruckten Produktcode erfassen. Führende Nullen und Groß-/Kleinschreibung bleiben erhalten. Die Zuordnung erfordert eine ausdrückliche Bestätigung. Ein Code kann nur einem Artikel zugeordnet sein; mehrere unterschiedliche Codes dürfen zum selben Artikel gehören. Korrekturen erfolgen durch begründetes Aufheben und erneutes Zuordnen. Die Historie bleibt erhalten.

Billomat-Artikelnummern werden nicht als Herstellerbarcodes angenommen. Der bisher gespeicherte Billomat-Katalog enthält kein Barcodefeld. Es erfolgen keine Änderungen an Billomat.

**Einzelartikel:** ein Code entspricht einer Lagereinheit. Bei Meterartikeln darf eine Entnahme bis zu drei Nachkommastellen besitzen.

**Verpackung:** den Inhalt ausdrücklich in Lagereinheiten angeben, beispielsweise 10 Stück je Karton. Entnahme von 2 Packungen bucht dann 20 Stück. Die Packungsanzahl muss ganzzahlig sein; die Umrechnung erfolgt auf dem Server und wird gegen den bestätigten Faktor geprüft.

**Seriennummern und zusammengesetzte Codes:** nicht zuordnen. GS1-Verbundcodes mit Trennzeichen/Application-Identifier-Schreibweise und URLs werden abgewiesen. Ein einfacher alphanumerischer Code verrät seine Bedeutung nicht zuverlässig; deshalb muss die Person am Etikett bestätigen, dass es ein Produkt-/Packungscode und keine individuelle Seriennummer ist. Keine automatische Klassifikation wird behauptet.

Unbekannte oder mehrdeutige Codes lösen keine Buchung aus. Überlange Codes werden abgewiesen, nicht auf eine möglicherweise passende Nummer gekürzt.

## Kamera und iPhone

ZXing Browser **0.2.1** ist vollständig lokal mitgeliefert. Zur Laufzeit wird weder ein CDN noch eine KI benutzt. Kameraaufnahmen werden nicht hochgeladen. Unterstützte Formatliste im Pilot: EAN-13, EAN-8, Code 39, Code 93, Code 128 und ITF. Die Browser-API `BarcodeDetector` ist nicht Voraussetzung.

Die Formatliste verhindert ZXings automatische Umwandlung von EAN-13 mit führender Null in eine verkürzte UPC-A-Ausgabe. Ein UPC-A-Etikett kann dadurch als 13-stellige EAN-Darstellung mit zusätzlicher führender Null gelesen werden. Codes nicht selbst numerisch umrechnen: am besten mit derselben Kamera/Scannerrepräsentation zuordnen. Abweichende Darstellungen bleiben unbekannt, bis eine weitere explizite Zuordnung vorgenommen wird. UPC-E, QR, DataMatrix und GS1-Auswertung sind im Pilot nicht eingeschaltet.

Kamera benötigt HTTPS, eine Browserberechtigung und passende Freigaben der Home-Assistant-Einbettung. Rückkamera wird bevorzugt, Audio nicht angefordert. Beim Stoppen, Verlassen oder Verbergen der Seite werden Kameratracks beendet. Bei verweigerter Berechtigung oder ungeeigneter Einbettung bleiben Texteingabe und Hardware-Scanner verfügbar. Die Kamera ist auf einem echten iPhone noch nicht abgenommen; auch reale Etikettenqualität und alle freigegebenen Symboltypen müssen dort geprüft werden.

Die bestehende HA-Ansicht wurde im Desktopbrowser lesend geprüft: HTTPS und ein Ingress-Frame derselben Herkunft, ohne explizites sandbox-/allow-Attribut. Das ersetzt weder die iPhone-WebView-Berechtigung noch einen Kamera-Gerätetest.

## Unklare Übertragung

Vor dem Absenden speichert die Seite Vorgangs-ID und unveränderte Formulardaten im `sessionStorage` dieses Browser-Tabs. Bei einem Reload bleiben sie erhalten. Bei fehlender Serverantwort wird die Buchung nicht als erfolgreich angezeigt. **Status prüfen** liest den Vorgang aus dem Journal. **Denselben Vorgang erneut senden** prüft zuerst den Status und verwendet anschließend dieselbe ID mit unveränderten Eingaben. Das vorhandene Lagerjournal verhindert eine doppelte Entnahme, auch wenn sich der Lagerstand oder eine Barcodezuordnung inzwischen geändert hat.

Bis zur Klärung keine neue Entnahme für denselben tatsächlichen Vorgang anlegen. Den Browser-Tab offen halten. Nach Schließen des Tabs oder Löschen des Browserspeichers kann die lokale Wiederholungsinformation fehlen; dann das Lagerjournal prüfen. Es gibt keine automatische Offlinebuchung. Ist der Browserspeicher nicht beschreibbar, sendet die JavaScript-Oberfläche keine Entnahme.

Eine bereits verwendete Vorgangs-ID mit abweichenden Eingaben wird als Konflikt gemeldet. Die Oberfläche behauptet dabei nicht, dass die ursprüngliche Buchung unterblieben sei. Bei eindeutig abgewiesenen neuen Eingaben den aktuellen Bestand laden und neu prüfen.

## Journal und Tests

Das bestehende atomare Lagerjournal speichert Auftrag, Artikel, Basismenge, Hauptlager, erfassten Namen, Code, Zuordnungsrevision, Packungsfaktor und ursprüngliche Mengenangabe. Namen sind weiterhin Selbstauskunft, keine zusätzlich authentifizierte Benutzeridentität. Bestandskorrekturen erfolgen wie bisher per Gegenbuchung oder begründeter Zählkorrektur.

Ältere App-Versionen verstehen die neuen Barcode-Journalaktionen nicht. Vor einem Downgrade die passende Sicherung der Vorversion wiederherstellen; kein Lagerjournal mit Barcodeereignissen ungeprüft in einer alten Version öffnen.

Automatisierte Prüfungen: führende Nullen, unbekannte/mehrdeutige/überlange Codes, unbestätigte Zuordnung, Packungsumrechnung, manipulierte Basismenge, unbekannter Bestand, Fremdreservierung, geänderte Zuordnung, zweimaliges Senden mit identischer ID, verlorene Antwort nach späterer Zuordnungsaufhebung, CSRF und Kontentrennung. Bestehende Lagerprüfungen decken konkurrierende Entnahmen und Reservierungen ab.

Browserlogik wird separat mit `node --test tests/barcode_browser.cjs` geprüft: Kamera nur nach Klick, doppelte Frames ohne Folgebuchung, verweigerte Kamera, identische Wiederholung nach Netzausfall, gesperrter Browserspeicher und tatsächliches lokales Decodieren eines synthetischen EAN-13 mit führender Null. Diese Tests ersetzen keine reale Kameraprüfung.

Primärquellen: [Billomat-Artikel](https://www.billomat.com/api/artikel/), [GS1-GTIN-Format](https://support.gs1.org/support/solutions/articles/43000734355-what-is-the-required-format-of-gtin-in-gs1-edi-standards-), [GS1 Application Identifiers](https://www.gs1.org/gs1-application-identifiers), [W3C Media Capture](https://www.w3.org/TR/mediacapture-streams/), [ZXing Browser](https://github.com/zxing-js/browser).
