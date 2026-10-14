# Exakte FTST-/FTronics-Produktbilder im Kundenportal

## Befund

`website_portal.snapshot()` erstellt die öffentlichen Positionen. Bilder werden dort bereits für feste Positionen unter `lines[].product_image_id` und für freigegebene Varianten unter `options[].product_image_id` eingefroren. Die bisherige automatische Zuordnung kennt Ajax-Geräte. FTST-/FTronics-Kameras, Rekorder und Zubehör bekommen über `ftst_product_images.py` ausschließlich bei eindeutigem Modellcode eine eigene Bild-ID.

Quelle ist der öffentliche Produktkatalog `https://www.ftsicherheitstechnik.com/produkte/<slug>` (Weiterleitung von www.ftst.eu). Die Website muss die 18 folgenden Bild-IDs freigeben, bevor diese HA-Erweiterung übernommen oder installiert wird:

| Modell | Bild-ID |
| --- | --- |
| FC-8D-PRO | ftst-fc-8d-pro |
| FC-8D-ZOOM | ftst-fc-8d-zoom |
| FC-6Z-MINI | ftst-fc-6z-mini |
| FB-8A-PRO | ftst-fb-8a-pro |
| FB-8A-MAX | ftst-fb-8a-max |
| FT-8C-PRO | ftst-ft-8c-pro |
| FT-8P-DUAL | ftst-ft-8p-dual |
| FP-8T-20X | ftst-fp-8t-20x |
| FN-16 | ftst-fn-16 |
| FS-30 | ftst-fs-30 |
| FC-8D | ftst-fc-8d |
| FB-8B | ftst-fb-8b |
| FP-8S-25X | ftst-fp-8s-25x |
| FE-6L | ftst-fe-6l |
| FN-8 | ftst-fn-8 |
| FN-32 | ftst-fn-32 |
| FN-64-PRO | ftst-fn-64-pro |
| FR-8X | ftst-fr-8x |

Modelle mit Bindestrich, Leerzeichen oder kompakter Schreibweise werden gleich behandelt. FC-8D, FC-8D-PRO und FC-8D-ZOOM bleiben verschiedene Produkte. Mehrfach-/widersprüchliche Modelle, unbekannte Erweiterungen sowie ausschließlich unter „kompatibel mit“/„passend für“ genannte Modelle bekommen kein Ersatzbild. Ajax-Zuordnung und Preise bleiben erhalten.

## Systemübergreifende Grenze

Ein Titel wie „8MP Bulletkamera mit Fixobjektiv 2,8 mm“ beweist kein konkretes Modell. Auch ähnliche technische Daten dürfen kein Modellfoto ersetzen. In solchen Fällen wird eine ausdrücklich geprüfte Produktbild-Auswahl aus der vorhandenen accountgebundenen Bilderbibliothek benötigt. Das gilt ebenso für Türsprechanlagen, Rekorderzubehör und andere Hardware. `app.normalize()` erhält derzeit keine Billomat-Artikel-ID; eine automatische globale Artikelbindung wäre deshalb nicht belastbar.

Die separat abgestimmte Erweiterung verwendet eigene eingefrorene Produktfotos zusätzlich zu den maximal vier Projekt-/Referenzbildern. Diese Modellzuordnung allein behebt keine bereits veröffentlichten Snapshots ohne Modellcode; bestehende Kundenrevisionen bleiben unveränderlich.

Diese Änderung aktiviert keinen HA-Zugang, verändert keine Add-on-Geheimnisse und schreibt keine Billomat-Angebote.

## Manuell freigegebene Produktfotos für alle Systeme

Im internen Kundenlink-Freigabeformular gibt es für jede Hardwareposition eine Auswahl aus der accountgebundenen Bilderbibliothek mit geschützter interner Vorschau. Logos und Dienstleistungspositionen werden ausgeschlossen. Die Freigabe bestätigt ausdrücklich die genaue Produktzuordnung. Die gespeicherte Auswahl ist an Account, Angebots-ID, Position und SHA256 von Titel/Beschreibung/Einheit gebunden. Mengen-/Preisänderungen ändern keine Produktidentität; andere Titel/Varianten/Beschreibungen verwerfen die automatische Wiederverwendung. Es handelt sich nicht um eine behauptete globale Billomat-Artikel-ID-Zuordnung.

Transportvertrag:

- `snapshot.product_images`: optional, höchstens 30 Deskriptoren `{id, caption}`.
- `lines[].product_photo_id` oder `options[].product_photo_id`: Verweis auf den ausdrücklich freigegebenen Deskriptor.
- Ein manueller Verweis ersetzt die statische `product_image_id` einschließlich des alten Beispielhinweises; beide Quellen stehen nicht gleichzeitig an derselben Position/Variante.
- Multipart `product:<id>` zusätzlich zu `pdf` und `image:<id>` für maximal vier Projektbilder.
- Kundenansicht lädt Fotos ausschließlich über den vorhandenen Cookie-geschützten Bild-Endpunkt der festgelegten Angebotsrevision.

Dateien werden aus der vorhandenen internen Bibliothek gelesen, ohne fremde Bild-URLs im Browser einzubauen. Die Normalisierung erstellt PNG-Vorschaubilder bis 128 KiB und entfernt EXIF/ICC/private Metadaten. Der Client prüft alle PDF-/Projekt-/Produktbildbytes, JSON und 128 KiB Multipart-Reserve gegen das bestehende globale Limit von 18 MiB **vor** der HTTP-Anfrage. 30 Deskriptoren bedeuten keine Freigabe für 30 Dateien à 2 MiB neben einer großen PDF.

Die Bibliothekscaption und internen Bildbeschreibungen werden nicht veröffentlicht. Öffentliche Captions entstehen ausschließlich aus dem bereits freigegebenen Positionstitel. Alle Zuordnungen und Bytes werden mit der neuen Kundenrevision eingefroren; alte Kundenlinks bleiben unverändert.

## Tag/Nacht-Regression

Die bisherige Wortsuche nach „Tag“ konnte eine Tag/Nacht-Kamera fälschlich als Ajax-TAG-Chip bebildern. Version 0.27.4 erkennt TAG nur als primären Produktnamen wie `Ajax TAG`, `TAG/Chip` oder `RFID Tag` nach einem optionalen `[ART-...]`-Präfix. Kamera-/Rekorder- und Tag/Nacht-Kontext erhält keine Chipabbildung. Generische Bulletkameras, Vierkanal-Rekorder, Switches, Festplatten, Boxen, Stecker und Kabel erhalten ohne belegtes Modell nur eine ausdrücklich freigegebene manuelle Zuordnung.

Freigabevoraussetzung: Website unterstützt zuerst die 18 IDs und den Produktfotovertrag. Dieser PR ist bis dahin ein Entwurf. Keine Installation oder Migration bestehender Kundenlinks wurde vorgenommen.
