# FTST Hermes für Home Assistant

Diese experimentelle App führt den Hermes-Agent-Prozess im eigenen Container auf dem HA-Server aus. Die Oberfläche ist ein kleiner FTST-Chat, aufgerufen über Home Assistant. Windows benötigt nur einen Browser. Hermes verwendet das vorhandene Ollama-Add-on. Ein neuer öffentlicher Port, Cloudflared-Änderungen oder das OpenAI-API-Konto sind für diese App nicht erforderlich.

1. Im FTST-App-Repository **FTST Hermes** installieren.
2. In **Konfiguration** die eigene 32-stellige **HA-Benutzer-ID** aus ATLAS → System als `owner_ha_user_id` eintragen. Die Adresse des lokalen Modellservers und Modellnamen mit FTST Lokale KI vergleichen.
3. Speichern, App starten und **Benutzeroberfläche öffnen**. „Hallo Hermes“ senden. Die erste erfolgreiche Modellantwort bestätigt die Verbindung.
4. Optionale Aufgabenverbindung: Auf der ATLAS-Seite muss die interne Aufgabenbrücke für denselben Besitzer aktiviert sein. Deren Token im maskierten Hermes-Feld `atlas_tasks_token` eintragen, den internen `atlas_tasks_host` kontrollieren und neu starten. Die Anzeige „konfiguriert“ allein ist kein Funktionstest. Den Auftrag „Leg eine Aufgabe an: Wartungsangebot vorbereiten“ ausführen und anschließend „Welche Aufgabe habe ich gerade angelegt?“ fragen. Die gespeicherte Aufgabe muss zusätzlich in ATLAS sichtbar sein.
5. Für Sprache erscheint **Sprachgespräch starten** in Browsern mit Web-Spracheingabe und Sprachausgabe. Die Erkennung kann den Dienst des Browserherstellers nutzen. Nach Erkennung wird das Mikrofon beendet, die Antwort gesprochen und danach eine neue Aufnahme gestartet. Die Funktion setzt ein sichtbares Fenster und Mikrofonfreigabe voraus. Eine Gerätesperre, Browserunterbrechung, zehn Minuten oder „Stopp“ beenden die Aufnahme. Keine zuverlässige Hintergrundfunktion auf dem iPhone.

Der Dialogverlauf bleibt im benutzergebundenen Hermes-Profil unter `/data/hermes`. Der Aufgabenadapter verwendet ausschließlich die drei Aufgabenwerkzeuge. Keine ATLAS-Anmeldedaten im Chat eingeben. Keine automatische Wiederholung von Schreibaufträgen nach Netzwerkabbrüchen.

Upstream: https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.6
