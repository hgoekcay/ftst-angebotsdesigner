## Digitalen Aufnahmebogen einlesen ab 0.26.0

Im Projekt die Technikeraufnahme öffnen und **Ausgefüllten PDF-Aufnahmebogen einlesen** aufklappen. Eine digital ausgefüllte FTST-Vorlage wählen, das Ersetzen der bisherigen Aufnahmedaten bestätigen und **PDF einlesen und prüfen** drücken. Der Import erkennt die Systemart über die Formularstruktur, nicht über den Dateinamen. Beide Seiten müssen vorhanden sein; maximal 5 MB. Ein Scan oder als Bild gedrucktes PDF enthält keine auslesbaren Formularfelder und wird als Foto erfasst.

Die Bedarfsliste von Seite 1 liefert Komponenten und Mengen. Nullmengen entfallen; unklare Mengen bleiben leer und behalten den Originaltext im Beleg. Detailzeilen von Seite 2 werden als Notizen übernommen und nicht doppelt addiert. Alle befüllten Felder stehen mit ihren Bezeichnungen in den Notizen, einschließlich Kontaktinformationen. Diese wählen keinen Billomat-Kunden und keinen E-Mail-Empfänger aus. Unbekannte Hersteller/Modelle manuell ergänzen. PDF-Prüfhäkchen bestätigen keine Übernahme in der App.

Der Import ersetzt nur die Aufnahme einschließlich ihrer Fotozuordnung. Projekt und Kalkulation bleiben bis zur explizit geprüften Übernahme unverändert. Fehlgeschlagene oder überlange Importe überschreiben keine Daten. Ältere gedruckte Hinweise, dass PDF-Import noch fehlt, sind mit dieser Version überholt. Fremde Formulare, Passwortschutz und gescannte Bögen werden nicht automatisch ausgelesen.
# Vom Techniker zum Angebotsentwurf

## Aufnahmebögen ab 0.24.8

Unter **Aufnahmebögen** in der Hauptnavigation stehen fünf ausfüllbare PDFs bereit: Alarmanlage / Ajax, Videoüberwachung, Zutrittssysteme, Schließzylinder und Türsprechanlagen. Sie sind auch aus der Technikeraufnahme erreichbar. Die Vorlagen können digital ausgefüllt oder gedruckt werden. Die Downloads verwenden die bestehende PDF-Vorbereitung innerhalb der angemeldeten App.

## Systemauswahl ab 0.25.0

Die Technikeraufnahme unterstützt Alarmanlage, Videoüberwachung, Zutrittssystem, Schließzylinder und Türsprechanlage. Zuerst die Systemart auswählen und **Systemauswahl und Angaben speichern** betätigen. Danach passen Checkliste, Schnellauswahl und technische Hinweise zur Systemart. Unter **Systemdetails** Blickbereiche, Rufzuordnung, Zylindermaße oder andere angefragte Details erfassen. Bei einem Wechsel bleiben vorhandene Komponenten erhalten und müssen erneut geprüft werden. Eine direkte bestätigte Übernahme während des Systemwechsels wird abgewiesen.

Bestehende Aufnahmen ohne Systemart bleiben Alarmaufnahmen. Ajax bleibt Alarmstandard. Für andere Systeme bleibt der Hersteller zunächst offen; Dahua und Ajax sind Nutzerpräferenzen, keine pauschale Zuordnung jeder Komponente. Ausdrücklich genannte Hersteller werden bewahrt. Artikelwahl und technische Kompatibilität müssen weiterhin geprüft werden. Ab 0.26.0 können außerdem digital ausgefüllte FTST-PDFs importiert werden.

Stand 0.16.0. Die Aufnahme lässt sich am Handy ohne KI direkt ausfüllen. Ein Handzettelfoto bleibt als ergänzende Quelle möglich.

1. Unter **Projekte** ein Projekt anlegen oder öffnen. **Ihr Weg zum Angebot** zeigt den gespeicherten Stand und den nächsten Schritt.
2. **Technikeraufnahme** öffnen und Kunde, Objektadresse, Serie, vorhandene Zentrale sowie Montageumfang erfassen. Unklare Angaben bleiben offen.
3. Unter **Ajax-Komponente schnell ergänzen** nur tatsächlich benötigte Typen auswählen. Jeder Klick ergänzt eine Zeile und speichert die bisherigen Eingaben. Eine Menge wird niemals vorausgefüllt. Mehrere gleichartige Geräte können getrennt nach Raum erfasst werden.
4. Menge, genaue Bezeichnung und optional **Raum / Montageort** eintragen, beispielsweise „Flur EG“ oder „Eingangstür“. Unter „Beleg / Ihre Ergänzung“ die Grundlage oder eine Zusatzinformation angeben. Nicht benötigte Zeilen vollständig leeren. Es sind höchstens 30 Komponenten möglich.
5. Mengen und Bezeichnungen prüfen, Bestätigungsfeld setzen und **Geprüfte Angaben ins Projekt übernehmen** wählen. Änderungen an Feldern oder Browser-Rückkehr setzen das Bestätigungsfeld zurück. Ohne Bestätigung bleiben die Daten nur in der Aufnahme.
6. **Kalkulation öffnen**: echte Billomat-Kunden und Artikel laden, Varianten zuordnen sowie Preise, Steuer und Leistungsumfang prüfen. Der Montageort steht in der Anforderung und ersetzt keine technische Artikelvariante. Er verändert keine Artikelstammdaten.
7. Kundentexte und Fotos prüfen. Eine kalkulierte PDF und die Billomat-Übergabe bleiben eigene, bewusste Schritte. Vor Übernahme werden Billomat-Konditionen erneut abgeglichen.

## Bedeutung der Übersicht

„Angaben übernommen“ belegt die Übernahme bestätigter Komponenten, nicht die Vollständigkeit aller Rückfragen. „Lokal geprüft“ gilt für den gespeicherten Kalkulationsstand. Spätere Anforderungen machen ihn veraltet. Ein bereits begonnener oder unklarer Billomat-Vorgang führt immer zur bestehenden Statusprüfung, nicht zu einer zweiten Anlage. „Entwurf angelegt“ bedeutet keine Freigabe, Beauftragung oder Versendung.

Alle Anzeigen lesen lokale gespeicherte Daten. Die Schnellauswahl und Übersicht benötigen keine KI-Credits und lösen keinen Billomat-Aufruf aus. Bestehende Aufnahmen ohne Montageort bleiben verwendbar. Es ist keine Datenbankmigration erforderlich.

## Anschließende Konzeptstufe

Die räumliche Zuordnung bildet die Grundlage für eine spätere Montageübersicht und bearbeitbare Kamera-/Alarmpläne. Ein Grundrisseditor, automatische Geräteplatzierung und eine automatische technische Freigabe sind in dieser Version noch nicht enthalten. Materialreservierung und interne Terminvorschläge werden weiterhin über **Material & Termine** nach dokumentierter Beauftragung bearbeitet.

