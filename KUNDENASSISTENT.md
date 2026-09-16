# Kundenassistent ab 0.5.0

Über **Kunden** oder **Kunden finden & anlegen** auf der Startseite:

1. Firmenname eingeben und zuerst **In Billomat suchen**. Vorhandene Kunden nicht erneut anlegen.
2. Für neue Firmen **Firma im Web suchen**: Firmenname und möglichst Ort eingeben. Die App zeigt bis zu drei Vorschläge mit verlinkten Quellen. Dafür muss `openai_api_key` in der Home-Assistant-App-Konfiguration eingerichtet sein; das konfigurierte Modell muss Websuche und strukturierte Ausgabe unterstützen (Standard `gpt-4.1`). Nur der eingegebene Suchtext wird zur Recherche übertragen, keine gespeicherten Billomat-Kunden oder Projektnotizen. Es entstehen OpenAI-API-Kosten.
3. **Diese Firma prüfen** öffnet die bearbeitbare Geschäftsanschrift. Name, Straße, Postleitzahl, Ort und Land prüfen. Eine Quelle ist keine Garantie für Aktualität oder Identität.
4. **Daten prüfen und Vorschau speichern** zeigt den genauen Übertragungsstand. Mit **Firmendaten korrigieren** zurück zur Bearbeitung; danach erneut Vorschau speichern.
5. Erst Checkbox und **Bestätigten Kunden in Billomat anlegen** übertragen diesen Stand. Direkt vorher wird der aktuelle Billomat-Bestand auf passende Namen/Anschriften geprüft, einschließlich archivierter Kunden. Es wird kein Angebot angelegt oder versandt. Kundennummer und kaufmännische Vorgaben vergibt Billomat nach den Kontoeinstellungen.
6. Im Angebotsentwurf **Artikel und Kunden aus Billomat laden**, dann den Kunden auswählen.

Ohne KI-Schlüssel bleiben bestehende Kundensuche und **Firmendaten manuell eingeben** verfügbar. Ein Browser-Login oder Codex-Guthaben ersetzt keinen API-Schlüssel der App.

Bei unklarem Übertragungsstatus (z. B. Verbindungsabbruch) sendet die App nicht erneut. Zuerst in Billomat prüfen, ob der Kunde bereits vorhanden ist. Der lokale Sperrdatensatz bleibt auch nach Neustart erhalten. Aktuell gibt es keine automatische Wiederfreigabe; eine erneute Anlage desselben Namens benötigt nach Prüfung eine gezielte technische Klärung. Ähnliche Namen können trotz Vorprüfung Dubletten sein und müssen vom Anwender geprüft werden.

## Billomat-Daten und Angebotsentwürfe

**Speichern** sichert Eingaben. **Billomat-Daten laden** ruft Artikel, Kunden, Steuern und Einheiten ab. Ein erfolgreicher zentraler Abruf steht neuen Entwürfen und dem Lager zur Verfügung. Bestehende Entwürfe behalten ihren Katalog bis zum ausdrücklich ausgelösten Aktualisieren, damit geprüfte Preise nicht unbemerkt wechseln. Bei fehlgeschlagenem Abruf bleibt der letzte gespeicherte Stand erhalten.

## Technische Prüfung

Automatisierte Tests mit simulierten API-Antworten prüfen Bestätigung, CSRF, konkurrierende Tabs, veraltete Vorschauen, Dubletten, Timeout/unklares Ergebnis, Quellenbindung und Katalogerhalt. Die Tests erzeugen keine echten Billomat-Kunden. Eine tatsächliche Kundenanlage wird erst mit vom Benutzer bestätigten echten Firmendaten durchgeführt.
