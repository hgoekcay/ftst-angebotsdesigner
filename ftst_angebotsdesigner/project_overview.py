"""Read-only project overview using existing reviewed workflow evidence."""
from html import escape
from urllib.parse import quote

from montage import overview
from project_workflow import progress


def render(store, identity, ingress):
    projects = store.records(identity, 'project')
    if not projects:
        return '<section class="card"><h2>Vorgangsübersicht</h2><p>Noch keine Projekte vorhanden.</p></section>'
    records = {kind: store.records(identity, kind) for kind in
               ('project_intake', 'quote', 'quote_transfer')}
    body = ('<section class="card"><h2>Vorgangsübersicht</h2><p>Gespeicherter interner Stand, '
            'kein Live-Abgleich. Ein Entwurf oder eine Verknüpfung ist keine Beauftragung. '
            'Termine, Material und Zahlungsstatus separat prüfen.</p></section>')
    for key, project in projects.items():
        intake = records['project_intake'].get(key)
        state = progress(project, intake, records['quote'].get(key), records['quote_transfer'].get(key))
        step = state['steps'][state['next_index']]
        assembly = overview(project, intake)
        root = 'projects/' + quote(str(key), safe='')
        target = ('offer/' + quote(str(step['offer_id']), safe='') if step.get('offer_id')
                  else root + '/' + step['path'])
        montage = ('Bestätigte Komponenten vorhanden' if assembly['accepted']
                   else 'Bestätigte Komponenten fehlen')
        if assembly['pending']:
            montage += ' · Neuere Aufnahme noch nicht übernommen'
        if assembly['accepted'] and assembly['missing_locations']:
            montage += f' · {assembly["missing_locations"]} Position(en) ohne Einbauort'
        body += (f'<section class="card"><h3><a href="{escape(ingress(root), quote=True)}">'
                 f'{escape(str(project.get("title") or "Unbenanntes Projekt"))}</a></h3>'
                 f'<p><strong>{escape(step["title"])}: {escape(step["state"])}</strong></p>'
                 f'<p>{escape(step["text"])}</p>'
                 f'<p>Offene Rückfragen: {len(state["questions"])}</p>'
                 f'<p><a class="btn" href="{escape(ingress(target), quote=True)}">'
                 f'{escape(step["action"])}</a></p><h4>Montagevorbereitung</h4>'
                 f'<p>{escape(montage)}</p><p><a href="{escape(ingress(root + "/montage"), quote=True)}">'
                 'Montageübersicht</a> · '
                 f'<a href="{escape(ingress(root + "/operations"), quote=True)}">Material & Termine</a></p>'
                 '<p class="muted">Keine technische Freigabe oder Terminbestätigung.</p></section>')
    return body
