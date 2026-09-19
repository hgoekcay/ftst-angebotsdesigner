# Lokale STRATO-Verbindung (0.12.0)

Der AngebotsDesigner kann neue Nachrichten von der separaten Home-Assistant-App FTST STRATO Mail übernehmen. Postfachpasswort und IMAP-Verbindung bleiben dabei ausschließlich in der Mail-App. Nachrichten und Anhänge werden anschließend in der lokalen Arbeitsliste gespeichert. Die bestehende lokale KI kann daraus Entwürfe vorbereiten; Versand und verbindliche Kundenzusagen werden nicht automatisch ausgeführt.

## Einrichtung

Beide Apps aktualisieren. In der Mail-App den internen Bridge-Zugang einschalten und einen zufälligen URL-sicheren Schlüssel von 43 bis 128 Zeichen lokal erzeugen. Im AngebotsDesigner `strato_provider: bridge`, denselben `strato_bridge_token` und `strato_imap_enabled: true` konfigurieren. `strato_imap_password` bleibt leer. Schlüssel nicht in Chat, Repository oder Protokolle kopieren. Beide Apps neu starten.

Die Mail-App stellt das Hauptpostfach (`primary`) und bis zu 20 weitere aktivierte Konten bereit. Weitere Konten werden ausschließlich dort unter `accounts` mit dauerhafter eindeutiger `id`, `email`, `password`, `folder` und `enabled` eingerichtet. Danach Mail-App neu starten. In der Mail-Arbeitsliste → STRATO-Postfächer für jedes Konto ausdrücklich einen eigenen Startpunkt setzen. Bereits vorhandene Mails werden ausgeschlossen. Danach ist ein manueller Abruf möglich. `strato_auto_import` und `strato_auto_ai` sind gesonderte, standardmäßig ausgeschaltete Optionen. Die Automatik darf ohne Startpunkt nicht importieren. Der Abrufabstand beträgt standardmäßig 300 Sekunden.

## Technische Grenzen

Interner fester Endpunkt `http://local-ftst-strato-mail:8098`; kein konfigurierbares Ziel, keine Proxy-Umleitung und kein Redirect. Zugriff per Bearer-Schlüssel. Die Verbindung bleibt im Home-Assistant-App-Netz und benötigt keine öffentliche Domain. HTTP im internen App-Netz ist nicht TLS-verschlüsselt: Administratoren und andere privilegierte Apps müssen vertrauenswürdig sein. Die beiden internen API-Routen dürfen nicht über Cloudflared/Reverse Proxy veröffentlicht werden.

Ein Abruf enthält höchstens 10 Nachrichten, 8 MiB pro Nachricht und 20 MiB insgesamt. JSON, Base64, UID-Reihenfolge und UIDVALIDITY werden geprüft. Fehler bestätigen keinen Cursor. Originale, Zuordnung und Cursor werden gemeinsam in einer Transaktion gespeichert; Wiederholungen überschreiben keine manuellen Antworten. Jedes Konto besitzt einen eigenen Cursor; Änderungen seiner E-Mail-Adresse oder seines Ordners werden bei bestehendem Startpunkt angehalten und erfordern technischen Abgleich. Entfernte oder deaktivierte Konten werden nicht weiter abgefragt. Konten lassen sich in der Oberfläche separat pausieren und fortsetzen. Identische Nachrichten in unterschiedlichen Konten erzeugen separate Arbeitsvorgänge mit korrekter Herkunft; Originaldateien werden weiterhin dedupliziert. Es gibt keinen automatischen Rückfall auf direkten IMAP-Zugriff.

Verbindungsaufbau und einzelne Antwortblöcke: Socket-Wartezeit maximal 15 Sekunden. Auf die ersten Antwortheader wird bis zu 85 Sekunden gewartet, damit der Mail-Abruf der anderen App abschließen kann. Antwortleseschleife mit 130 Sekunden Gesamtlaufzeitprüfung. Betriebssystem-DNS-Auflösung kann unabhängig davon länger blockieren. Es werden keine Nachrichtentexte oder Authentifizierungsfehler des Servers in Fehlermeldungen ausgegeben. Sicherungen der HA-Konfiguration enthalten die Schlüssel und sind entsprechend zu schützen.

## Automatische Verarbeitung

Nach einmaligem Startpunkt holt der Hintergrunddienst standardmäßig alle fünf Minuten bis zu zehn neue Nachrichten. Bei Fehlern steigt die Wartezeit bis maximal eine Stunde; der gespeicherte Abrufstand wird nicht vorgerückt. Ein Prozess-Lock verhindert doppelte Hintergrunddienste. Manuelle Abrufe nutzen dieselbe Sperre wie die Automatik.

Pro Hintergrunddurchlauf wird höchstens eine noch unbearbeitete importierte Mail lokal ausgewertet. Nur vollständiger kurzer Klartext ohne MIME-Warnungen wird verwendet. HTML, PDFs und andere Anhänge werden nicht ausgewertet. Kategorien und Antworten bleiben Vorschläge; weder Versand noch Billomat-Buchung werden ausgelöst. Manuelle Bearbeitung wird über Revisionsprüfungen geschützt. Fehlgeschlagene oder unterbrochene KI-Auswertungen werden nicht unbegrenzt wiederholt; sie können im Vorgang bewusst erneut gestartet werden.

## Installation auf dieser FTST-Instanz

`scripts/install_local_mail.py` ist für Advanced SSH dieser Instanz bestimmt. Schritte `backup`, `deploy`, `connect`, `verify` nacheinander ausführen. Es erstellt eine verschlüsselte Teilsicherung beider Apps. Der Wiederherstellungsschlüssel bleibt ausschließlich auf dem Server unter `/share/ftst-local-mail-recovery-0.12.0/backup-password` (Dateirechte0600); den Schlüssel getrennt von der Sicherung sicher aufbewahren. Das Skript gibt keine Geheimnisse aus, erhält vorhandene App-Optionen und erzeugt den gemeinsamen internen Schlüssel lokal. Die beiden Versionsstände werden vor der Verbindung geprüft. Danach den Startpunkt über die STRATO-Eingangsseite setzen.

Keine neue Cloudflared-Route und kein ChatGPT-Mailzugriff sind für diesen lokalen Ablauf erforderlich. Die Mail-App bietet weiterhin ihren getrennten OAuth-Dienst; seine öffentliche Freigabe ist nicht Teil dieser Installation.
