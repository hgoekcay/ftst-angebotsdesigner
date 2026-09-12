# Bildbestand 0.3.0

Zwölf vom Nutzer gelieferte Originaldateien werden unverändert unter `ftst_angebotsdesigner/assets` mitgeliefert. Die App benötigt dafür keinen Zugriff auf OneDrive, NAS, Instagram oder Ajax. `asset_library.py` ordnet stabile IDs, Kategorien und Quellenarten zu.

FT Sicherheitstechnik ist die Firmenmarke. Das breite Logo erscheint im App-Kopf und als PDF-Standard, sofern noch keine Logoauswahl gespeichert ist. Vorhandene eigene Logos und ausdrücklich gespeichertes „Ohne Logo“ behalten Vorrang. FTronics ist die Produktmarke für Kameras und eigene Produkte. Das Produktlogo steht bereit; bestehende Montagefotos wurden nicht nachträglich umbeschriftet.

Unter „Fotos auswählen“ stehen acht Motive mit Vorschauen bereit. Die Auswahl wird pro Billomat-Konto und Angebot gespeichert. Keine automatische Ergänzung von Fotoseiten zu bestehenden Angeboten. Höchstens acht Bilder, jedes auf einer eigenen PDF-Seite. Firmenlogos werden in dieser Fotoauswahl ausgeblendet; Logoauswahl unter Firmendaten. Eigene Uploads bleiben im persistenten Datenverzeichnis.

Montagefotos sind als FTST-Originalfoto, die beiden gelieferten AdobeStock-Motive als Symbolfoto und die Videografik als Hinweisgrafik gekennzeichnet. Keine KI-generierten Motive. Die gewünschten vier Motive je Gewerk sind noch nicht vollständig vorhanden: Video zwei Montagefotos plus Hinweisgrafik, Zutritt zwei Fotos, Türsprechanlage zwei Fotos, ein allgemeines Sicherheitsmotiv. Für Alarm, Rauch und Brandwarnung fehlen weitere geeignete Originale.

## Prüfung

55 Tests einschließlich Erkennung, Speicherung, Angebotsentwurf, Bilddateien, Kontentrennung, Logoabschaltung, Ingress-Links, fehlender Dateien und PDF-Bildern. Fünfseitiges Musterangebot lokal gerendert und visuell geprüft.

## Noch in Home Assistant prüfen

Nach Backup und Installation: Add-on-Version 0.3.0, bestehende Firmendaten/Projekte, alle Bildvorschauen über Ingress, Bildauswahl nach Neustart, PDF im separaten Tab, Live-Billomat-Katalog und Kundenpreisgruppen. Diese neue Fassung wurde noch nicht in HA installiert.
