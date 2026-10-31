## 0.8.3

- Eingehende Anhänge werden als ungeprüfte Eingangsbelege bezeichnet. PDF-Erkennung unterstützt eindeutige Nummer-/Datumszeilen, Währungszeichen vor Beträgen und identische wiederholte Rechnungsnummern; widersprüchliche Angaben bleiben offen. Bestehende Belege werden nicht automatisch neu ausgewertet.

- Bereits angenommene Sprachaufträge liefern ihre Antwort auch nach dem Beenden des Gesprächs oder einem Ansichtswechsel als Text nach, solange die Seite geöffnet bleibt. Mikrofon und automatische Wiedergabe bleiben ausgeschaltet; ein neueres Gespräch wird nicht beeinflusst.
- Ältere bekannte offene Billomat-Rechnungen werden unabhängig vom Entdeckungszeitraum erneut abgefragt, höchstens 25 pro Abgleich. Unvollständige Zahlungsstandsprüfungen bleiben sichtbar.
- Ein vollständiges Neuladen verwirft weiterhin die Chatansicht; gespeicherte Ergebnisse bleiben unter Aufgaben abrufbar. Buchhaltung bleibt eine Vorbereitung ohne Bankabgleich.

## 0.8.2

- Gespräch steht im Mittelpunkt: neue ATLAS-Kugel mit Zuständen für Start, Zuhören, Verarbeitung, Sprechen und Unterbrechung; reduzierte Animation auf Wunsch des Geräts.
- Kurze Verbindungsfehler beim Abholen einer Antwort werden bis zu dreimal erneut versucht. Bereits übermittelte Aufträge werden dabei nicht erneut gestartet.
- Zeitlimit auch beim Lesen einer hängen gebliebenen Antwort; Stoppen verhindert verspätete Wiedergabe.
- Test auf dem eigenen Gerät erforderlich: diese Version garantiert keine Behebung gerätespezifischer Mikrofon- oder Audiofehler.

## 0.8.1

- Gesprächsstart mit lokaler Begrüßung und erkennbaren Startphasen.
- Sprachausgabe im beim Start freigegebenen Audiokontext; klare Meldungen bei blockierter Ausgabe oder fehlendem Mikrofon.
- „Jetzt antworten“ beendet die Aufnahme ausdrücklich, wenn die automatische Sprechpausenerkennung nicht greift.

## 0.8.0

- Ausdrücklich einschaltbarer Gesprächsmodus: lokal zuhören, eine Anfrage bearbeiten und die Antwort vorlesen; Stoppen beendet die Aufnahme und weitere Gesprächsrunden.
- Gesprochene Aufträge für Aufgaben, Tagesüberblick und Monatsvorbereitung mit bestehenden Benutzerrechten; wiederholte Übertragung derselben Anfrage führt nicht zu doppelten Aufträgen.
- Aufnahme mit Textprüfung und manuelles Vorlesen bleiben verfügbar. Mikrofon und Sprachausgabe wechseln sich ab; kein dauerhaftes Hintergrundmikrofon.

## 0.7.3

- Für große Downloads gilt ein eigenes begrenztes Übertragungszeitfenster; die kurzen Zeitlimits beim Lesen von Anfragen bleiben unverändert.

## 0.7.2

- Monatsausgaben können den begrenzten Gesamtbestand bis 2.000 Belegen enthalten. Die 100-MiB-Prüfung für Originale und Prüfdaten bleibt erhalten; keine stille Kürzung auf 100 Belege.

## 0.7.1

- Bekannte Exportgrenzen und Originaldatei-Probleme im fehlgeschlagenen Vorbereitungsschritt gezielt anzeigen; unbekannte Fehler bleiben geschützt.

## 0.7.0

- Tagesüberblick und Monatsvorbereitung als feste Arbeitsabläufe mit dauerhaftem Schrittstatus und geschütztem Downloadpaket.
- Telegram: `/briefing`, `/vorbereiten YYYY-MM`, `/auftraege` und `/auftrag ID`.
- Lokale Spracheingabe mit Whisper, Prüfung des Transkripts vor dem Senden und ausdrückliches Vorlesen mit Piper. Audiodatei-Upload als Alternative zum Mikrofon.
- Sprachzugriff nur für den konfigurierten Eigentümer; höchstens 60 Sekunden und 5 MiB. Keine automatische Ausführung gesprochener Befehle.

## 0.6.1

- Veraltete fest eingetragene Versionsnummer aus der Fußzeile entfernt. Unter System wird die tatsächliche Backend-Version angezeigt.

## 0.6.0

- Firmenwissen mit Schlagwörtern suchen und mit nachvollziehbarer Versionshistorie korrigieren. Gleichzeitige Änderungen werden erkannt.
- Aufgaben mit eigenen Wissenseinträgen verknüpfen; passende aktuelle Notizen werden lokal als Antwortkontext verwendet.
- Rohmails bis 32 MiB und Mailbatches bis 40 MiB mit STRATO 0.3.1 verarbeiten. Einzelne Beleganhänge bleiben auf 8 MiB begrenzt. Anmelde- und Größenfehler werden gezielt angezeigt.

# 0.5.1

- Include the bookkeeping list-limit hint in the shipped HTML.
- Verify JavaScript element references against real HTML in CI.

# 0.5.0

- Owner-scoped selection of configured mailboxes and bounded invoice attachment import.
- Read-only Billomat invoice snapshots and original PDFs, resumable periodic synchronization.
- Immutable original documents, review history, explicit missing information and monthly ZIP exports.
- AI Bookkeeping documents/1 interchange; uncertain tax treatment remains blocked for review.
- Telegram `/op`, `/belege`, `/buchhaltung` and optional daily Berlin-time summary.
- Personal revocable employee upload links on a separate HTTPS-proxied upload-only service.
- New integrations and public listener remain disabled until explicitly configured.

## 0.4.1

- Bei vorübergehenden Datenbankfehlern wird nur das Speichern eines bereits berechneten Auftragsergebnisses wiederholt. Die KI-Anfrage wird nicht erneut ausgeführt.

## 0.4.0

- Neue Apple-inspirierte Oberfläche mit Systemschrift, adaptivem Hell-/Dunkelmodus und mobiler Navigation.

- Optionale OpenAI-Beratung mit Websuche und anklickbaren Quellen. Keine Verbindung zu einem privaten ChatGPT-Chat.
- Automatischer Modus für Recherchebegriffe und lokale Modellfehler; „Nur lokal“ verhindert Online-Anfragen.
- Hintergrundaufträge bleiben beim Schließen der Oberfläche aktiv. Ergebnisse sind bis zu sieben Tage unter Aufgaben abrufbar.
- Begrenzte Online-Anfragen pro UTC-Tag, keine automatische Wiederholung unsicher abgeschlossener API-Aufrufe.
- Online-Kontext standardmäßig nur die aktuelle Frage; Firmenprofil separat zuschaltbar. Postfach, Erinnerungen und Chatverlauf werden nicht automatisch übertragen.
- Telegram: /online FRAGE, /lokal FRAGE und automatische Auswahl.

## 0.3.0

- Neuer Bereich E-Mails mit lesender STRATO-Vorschau für einen explizit freigegebenen HA-Benutzer.
- Bis zu 10 Nachrichten im gewählten Zeitraum, älteste zuerst; unvollständige Vorschauen und gekürzte Texte sind gekennzeichnet.
- Lokale Zusammenfassungen und Antwortentwürfe, ohne Versand, Mailboxänderungen oder automatisches Speichern ins Firmenwissen.
- Postfachzugriff standardmäßig aus. Vorschau bleibt nur im Arbeitsspeicher; Auswahl-IDs nach 30 Minuten, neuem Abruf oder Neustart ungültig.
- E-Mail-Auswertung erhält keine privaten Firmenprofile oder gespeicherten Notizen; Roh-HTML und externe Bilder werden nicht geladen.

# 0.2.4

- Explizite Qwen3-4B-Instruct-2507-Q4_K_M-Variante für direkte Antworten unterstützen.
- Instruct ohne Denk-Prefill ansteuern; vier CPU-Threads und 384 Antworttokens.
- Vorhandenes Modell bleibt erhalten; Instruct-Modell muss lokal vorbereitet sein.

# 0.2.3

- Aufeinanderfolgende Telegram-Nachrichten nicht mehr durch Zehn-Sekunden-Sperre verwerfen.
- Aufgaben auch mit tasks oder Aufgaben abrufen; KI-Fragen sofort bestätigen.
- Antwortbudget auf 768 Tokens erhöhen, unvollständige Antworten weiterhin abweisen.

# 0.2.2

- Abgeschlossene Modellantworten von separaten oder vorangestellten Denk-Ausgaben trennen.
- Leere, unvollständige oder weiterhin markierte Antworten bleiben gesperrt.

# 0.2.1

- Telegram-Felder optional: ID-Ermittlung lässt sich ohne Telegram-Nutzer-ID speichern.
- Verbindungsstatus im Protokoll ohne Token oder Nachrichteninhalte.

# 0.2.0

- Optionale Telegram-Textanbindung per Long Polling, standardmäßig deaktiviert.
- Explizite Zuordnung privater Telegram-ID zum gespeicherten HA-Profil.
- /id ohne Wissenszugriff; /tasks und /remember für freigegebenen Nutzer.
- Qwen-Korrektur aus 0.1.1 enthalten, Live-Abnahme weiterhin erforderlich.

# 0.1.0

- Erste separate ATLAS-App für vorhandenes lokales Ollama.
- Mobile deutsche Oberfläche mit Chat, Wissen, Aufgaben und Systemstatus.
- Explizites, einsehbares Gedächtnis statt ungeprüfter automatischer Übernahme.
- Keine externen Aktionen; fehlende Kommunikationskanäle klar gekennzeichnet.
