"""Read-only library of printable, fillable technician forms."""

TEMPLATES = (
    ('Alarmanlage / Ajax', 'Ajax', 'Zentrale, Melder, Sirenen, Bedienteile und Montageorte.'),
    ('Videoüberwachung', 'Videoueberwachung', 'Kamerastandorte, Aufzeichnung, Netzwerk und Montage.'),
    ('Zutrittssysteme', 'Zutrittssysteme', 'Türen, Leser, Berechtigungen und Systemanbindung.'),
    ('Schließzylinder', 'Schliesszylinder', 'Türen, Zylindermaße, Ausführung und Schließberechtigungen.'),
    ('Türsprechanlagen', 'Tuersprechanlagen', 'Rufziele, Innen- und Außenstationen, Verkabelung und Türöffner.'),
)


def register(app, base, ingress, escape):
    @app.get('/intake-templates')
    def intake_templates():
        body = ('<div class="card"><div class="eyebrow">Für den Termin vor Ort</div>'
                '<h1>Aufnahmebögen</h1><p>Passende Vorlage herunterladen, digital ausfüllen '
                'oder ausdrucken. Kundendaten können später ergänzt werden.</p></div><div class="grid">')
        for title, suffix, description in TEMPLATES:
            filename = f'FTST-Technikeraufnahme-{suffix}.pdf'
            body += (f'<section class="card"><h2>{escape(title)}</h2><p>{escape(description)}</p>'
                     f'<a class="btn" style="background:#16803c" data-pdf="{filename}" '
                     f'href="{ingress("static/" + filename)}">PDF herunterladen</a></section>')
        body += ('</div><div class="card"><h2>Von der Aufnahme zum Leistungsvorschlag</h2>'
                 '<p>Nur neu benötigte Mengen eintragen und offene Angaben kennzeichnen. '
                 'Fotos und Typenschilder den jeweiligen Einbauorten zuordnen.</p>'
                 '<p>Die ausgefüllte PDF wird noch nicht automatisch eingelesen. Angaben können '
                 'im KI-Chat als Text oder lesbares Foto eingebracht werden. Erkannte Mengen, '
                 'Kunde und konkrete Billomat-Artikel anschließend prüfen.</p>'
                 '<p>Die bestehende strukturierte Technikeraufnahme ist auf Ajax-Alarmanlagen '
                 'ausgerichtet. Andere Systeme werden durch diese Vorlagen nicht automatisch '
                 'als Ajax-Anlage zugeordnet.</p>'
                 f'<a class="btn light" href="{ingress("chat")}">Zum KI-Chat</a>'
                 f'<a class="btn light" href="{ingress("projects")}">Zu den Projekten</a></div>')
        return base('Aufnahmebögen', body)

