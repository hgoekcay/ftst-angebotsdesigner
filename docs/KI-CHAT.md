# FTST Chat (0.23.0)

Unter **KI-Chat** eine Unterhaltung starten. Beispiel: „Erstelle einen Leistungsvorschlag für Müller GmbH: 6 Bewegungsmelder und 2 Türkontakte. E-Mail einkauf@example.org.“

Der Chat speichert Gespräch, Kunde, Anforderungen und Kalkulation. Textverarbeitung nutzt den vorhandenen lokalen Dienst mit qwen3:4b; keine Cloud-Ausweichverarbeitung. Das kleine lokale Modell ist auf die Angebotsaufnahme begrenzt, kein allgemeiner autonomer Computeragent.

## Ablauf

1. Anforderungen schreiben oder Sprachnotiz hochladen/aufnehmen. Erkannten Sprachtext vor dem Senden prüfen.
2. Kunden und konkrete Varianten aus Billomat wählen. Eindeutige vollständige Artikelbezeichnungen/Artikelnummern können automatisch zugeordnet werden; allgemeine „Bewegungsmelder“ bleiben zur Variantenwahl offen. Ajax gilt für Alarmanlagen.
3. Korrekturen im Chat eingeben. Die Kalkulation verwendet ausschließlich Katalogpreise und bestehende Kundenkonditionen. Steuerfragen und fehlende Angaben verhindern eine fertige Summe.
4. PDF-Entwurf prüfen. Die Prüfung bestätigen (auch „Ja, passt so“ ist möglich). Anlage in Billomat nochmals konkret bestätigen. Bestehende Übertragungssperren und Rückleseprüfung gelten weiter.
5. Den geprüften Billomat-Entwurf ausdrücklich freigeben. Die App vergibt die Angebotsnummer über Billomat, versendet dabei nichts. Nach ungeklärter Freigabe nur den Status prüfen, kein erneuter PUT.
6. Empfänger prüfen und E-Mail samt endgültiger PDF vorbereiten. **E-Mail & PDF prüfen und senden** öffnet die bestehende Versandvorschau. Dort Versand ausdrücklich bestätigen. Allgemeine Chat-Zustimmung sendet keine Nachricht.

Neukunden: vollständigen Namen, Straße, PLZ, Ort und Land im Chat nennen. Die angezeigten Daten zur Kundenanlage bestätigen. Dublettenprüfung und dauerhafte Übertragungssperre gelten. Die E-Mail-Adresse für den Versand wird im Chat gespeichert; die Kundenanlage übernimmt über den bestehenden Kundenassistenten Name/Anschrift.

## Sprache und Grenzen

Audio: maximal 12 MB und 120 Sekunden. FFmpeg dekodiert lokal, danach wird ausschließlich der interne Home-Assistant-Whisper-Dienst `core-whisper:10300` angesprochen. Der Dienst muss laufen und Sprache Deutsch unterstützen. Originalaudio liegt nur während der Verarbeitung temporär vor und wird entfernt. Transkript wird im Chat gespeichert und bleibt vor der Übernahme bearbeitbar.

Browseraufnahmen benötigen Mikrofonfreigabe und MediaRecorder. Manche Home-Assistant-Webviews blockieren Mikrofonzugriff. Dann Audiodatei hochladen oder Tastatur-Diktat verwenden. Kein automatischer Zugriff auf das Mikrofon.

Maximal 20 Komponenten, 2000 Zeichen je Chatnachricht; begrenzter Modellkontext. Lange Gespräche mit dem ausführlichen Entwurf abschließen oder neuen Chat starten. Verarbeitung läuft im Hintergrund. Nach Neustart werden Aktionen nicht automatisch wiederholt. Nach einer Unterbrechung bei externen Aktionen den angezeigten Status abgleichen.

Der Chat verändert keine bereits angelegten Billomat-Angebote. Für einen anderen Leistungsumfang einen neuen Chat beginnen oder den bestehenden Billomat-Entwurf gezielt außerhalb des Chats bearbeiten. Ein nachträglich veränderter Billomat-Entwurf wird nicht ungeprüft freigegeben.

## Prüfung / Daten

Chat und Projekt sind auf das Billomat-Konto begrenzt. Formulare verwenden CSRF-Token und Revisionen. Hintergrundaufträge vergleichen Projekt-, Kalkulations- und Übertragungssnapshots. Modelltexte können keine externen Aktionen auslösen. Vor Installation App inklusive Daten sichern; nach Wiederherstellung älterer Backups externe Übertragungsstände abgleichen.

Protokolle: [Wyoming](https://github.com/OHF-Voice/wyoming), [Billomat-Angebote und Abschluss](https://www.billomat.com/api/angebote/).

