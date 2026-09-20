"""Read-only installation preparation from explicitly accepted technician data."""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from flask import abort

from materials import account


def overview(project, intake=None):
    analysis = project.get('analysis') or {}
    rows = analysis.get('components') or []
    accepted = (analysis.get('provider') == 'technician-reviewed'
                and analysis.get('user_confirmed') is True and bool(rows))
    groups = OrderedDict()
    if accepted:
        for index, row in enumerate(rows, 1):
            try:
                count = Decimal(str(row.get('quantity', '')))
                if (row.get('user_confirmed') is not True or not count.is_finite() or count <= 0
                        or not str(row.get('description') or '').strip()):
                    accepted = False
                    break
            except (InvalidOperation, ValueError):
                accepted = False
                break
            location = str(row.get('location') or '').strip()
            # The original label avoids duplicating the room suffix from quote search.
            label = str(row.get('source_description') or row['description'])
            groups.setdefault(location, []).append(dict(
                number=index, description=label, quantity=format(count, 'f').replace('.', ','),
                evidence=str(row.get('evidence') or '')))
    if not accepted:
        groups.clear()
    pending = bool(intake and (intake.get('status') != 'applied' or intake.get('review_required')
                              or intake.get('source_changed')))
    return dict(accepted=accepted, groups=groups, pending=pending,
                fields=(project.get('intake_fields') or {}) if accepted else {},
                questions=analysis.get('questions', []) if accepted else [],
                count=len(rows) if accepted else 0,
                missing_locations=sum(len(items) for name, items in groups.items() if not name))


def register(app, base, ingress, escape, get_store):
    @app.get('/projects/<key>/montage')
    def montage_overview(key):
        store, identity = get_store(), account()
        project = store.record(identity, 'project', key)
        if project is None:
            abort(404)
        intake = store.record(identity, 'project_intake', key)
        value = overview(project, intake)
        project_url = ingress('projects/' + key)
        body = (f'<div class="back montage-actions"><a href="{project_url}">← Projekt</a></div>'
                f'<section class="card"><div class="eyebrow">Interne Montagevorbereitung</div>'
                f'<h1>Montageübersicht</h1><h2>{escape(project.get("title"))}</h2>'
                '<p>Grundlage ist die ausdrücklich übernommene Technikeraufnahme. '
                'Beauftragung, konkrete Artikelvarianten und technische Ausführung separat prüfen.</p>')
        if not value['accepted']:
            body += ('<p role="status">Noch keine bestätigte Komponentenliste vorhanden. '
                     'Bitte die Technikeraufnahme prüfen und ausdrücklich ins Projekt übernehmen.</p>')
        else:
            body += f'<p>{value["count"]} bestätigte Positionen · {value["missing_locations"]} ohne Einbauort</p>'
            if value['pending']:
                body += ('<p class="montage-warning" role="status"><strong>Neuere Aufnahme noch nicht übernommen.</strong> '
                         'Diese Übersicht zeigt weiterhin den zuletzt bestätigten Projektstand. '
                         'Änderungen vor der Montage abgleichen und erneut bestätigen.</p>')
            body += '<div class="grid">'
            for label, field in [('Kunde', 'customer_name'), ('Objektadresse', 'object_address'),
                                 ('Hersteller', 'manufacturer'), ('Serie / Variante', 'variant')]:
                body += f'<div><strong>{label}</strong><p class="montage-text">{escape(value["fields"].get(field) or "Offen")}</p></div>'
            body += '</div>'
        body += (f'<p class="montage-actions"><a class="btn light" href="{project_url}/intake">Aufnahme prüfen</a>'
                 f'<a class="btn light" href="{project_url}/operations">Material & Termine</a></p></section>')
        if value['accepted']:
            body += '<p class="montage-actions"><button class="btn" id="montage-print" type="button">Übersicht drucken</button></p>'
            for location, items in value['groups'].items():
                body += f'<section class="card montage-room"><h2>{escape(location or "Einbauort offen")}</h2><ul class="montage-components">'
                for row in items:
                    body += (f'<li><div><span class="muted">Position {row["number"]}</span>'
                             f'<h3>{escape(row["quantity"])} × {escape(row["description"])}</h3>'
                             f'<p class="montage-text">{escape(row["evidence"])}</p></div></li>')
                body += '</ul></section>'
            body += '<section class="card"><h2>Montage und Einsatz</h2>'
            for label, field in [('Montage / Arbeitsumfang', 'installation'), ('Anfahrt / Einsatzort', 'travel'),
                                 ('Weitere Hinweise aus der Aufnahme', 'notes')]:
                body += f'<h3>{label}</h3><p class="montage-text">{escape(value["fields"].get(field) or "Noch offen")}</p>'
            choices = {'central': ('Zentrale vorhanden', {'yes': 'Ja', 'no': 'Nein'}),
                       'siren': ('Sirene vorhanden / gewünscht', {'yes': 'Ja', 'no': 'Nein'}),
                       'area': ('Bereiche', {'inside': 'Innen', 'outside': 'Außen', 'both': 'Innen und außen'})}
            for field, (label, options) in choices.items():
                body += f'<p><strong>{label}:</strong> {options.get(value["fields"].get(field), "Unklar")}</p>'
            body += '</section><section class="card"><h2>Vor dem Einsatz klären</h2><ul>'
            if value['missing_locations']:
                body += '<li>Fehlende Einbauorte mit dem Techniker ergänzen und bestätigen.</li>'
            body += ''.join('<li>' + escape(str(question)) + '</li>' for question in value['questions'])
            body += ('<li>Konkrete Gerätevarianten, Zubehör und Leitungswege mit dem beauftragten Umfang abgleichen.</li>'
                     '<li>Materialverfügbarkeit und Termin unter „Material & Termine“ prüfen.</li>'
                     '</ul><p class="muted">Diese Übersicht reserviert kein Material, bestätigt keinen Auftrag '
                     'und dient nicht als technische Freigabe oder Abnahmeprotokoll.</p></section>')
        body += ('<style>.montage-text{white-space:pre-wrap}.montage-components{list-style:none;padding:0!important}'
                 '.montage-components>li{border-top:1px solid #e2e5e7;padding:14px 0;break-inside:avoid}'
                 '.montage-components h3{margin:6px 0}.montage-warning{border-left:4px solid #d71920;padding:12px;background:#fff4f4}'
                 '@media print{@page{size:A4;margin:15mm}body{background:white;font-size:11pt}.appnav,.montage-actions{display:none!important}'
                 '.top{background:white;color:black;border:0}.topin{padding:0}.wrap{padding:0;margin:12px 0;max-width:none}'
                 '.card{box-shadow:none;border:0;border-radius:0;padding:0;margin:0 0 18px}.grid{display:block}.grid>div{display:inline-block;vertical-align:top;width:48%}'
                 'h2,h3{break-after:avoid}.montage-room h2{border-bottom:1px solid #aaa}.montage-warning{border:1px solid #999}}</style>'
                 f'<script defer src="{ingress("static/montage.js")}"></script>')
        # Do not mix a late edit into an otherwise consistent displayed snapshot.
        if store.record(identity, 'project', key) != project or store.record(identity, 'project_intake', key) != intake:
            abort(409, 'Die Aufnahme wurde während des Ladens geändert. Bitte die Montageübersicht neu öffnen.')
        response = app.make_response(base('Montageübersicht', body))
        response.headers['Cache-Control'] = 'no-store'
        return response
