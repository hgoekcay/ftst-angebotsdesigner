"""Persistent app navigation with local, deterministic return destinations."""
from html import escape

from flask import current_app, request
from werkzeug.exceptions import HTTPException

SECTIONS = [('offers', 'Angebote', '<path d="M6 3h9l3 3v15H6zM9 9h6M9 13h6M9 17h4"/>'),
            ('materials', 'Fotos', '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="2"/><path d="m3 18 6-6 4 4 3-3 5 5"/>'),
            ('company', 'Firma', '<path d="M4 21V3h16v18M8 7h2m4 0h2M8 11h2m4 0h2M10 21v-6h4v6"/>'),
            ('more', 'Mehr', '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>')]
MORE = [('documents', 'Rechnungen & Lieferscheine'), ('intake-templates', 'Aufnahmebögen'),
        ('inventory', 'Lager'), ('materials', 'Bilder'), ('company', 'Firma'),
        ('email-settings', 'E-Mail-Einstellungen'),
        ('portal/responses', 'Kundenantworten'), ('billomat', 'Billomat')]


def navigation(ingress):
    path = request.path.strip('/')
    group = path.split('/')[0]
    active = {'': 'offers', 'offer': 'offers', 'project': 'projects', 'customer': 'customers',
              'email-delivery': 'offers'}.get(group, group)
    if active not in ('offers', 'materials', 'company'):
        active = 'more'
    tabs = '<nav class="bottom-tabs" aria-label="Hauptnavigation">'
    for route, label, icon in SECTIONS:
        tabs += ('<a href="' + escape(ingress(route), quote=True) + '"' +
                 (' aria-current="page"' if active == route else '') +
                 '><svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + icon + '</svg>' + label + '</a>')
    tabs += '</nav>'
    parent = '/'
    parts = path.split('/')
    if group == 'offer' and len(parts) > 1:
        parent = '/offer/' + parts[1] if len(parts) > 2 else '/offers'
    elif group == 'email-delivery':
        parent = '/email-delivery/' + parts[1] if len(parts) > 2 else '/offers'
    else:
        adapter = current_app.url_map.bind('localhost')
        for end in range(len(parts) - 1, 0, -1):
            candidate = '/' + '/'.join(parts[:end])
            try:
                adapter.match(candidate, method='GET')
                parent = candidate
                break
            except HTTPException:
                continue
    back = '' if not path else ('<div class="app-return"><a href="' + escape(ingress(parent.lstrip('/')), quote=True) +
                               '">← Zurück</a><a href="' + escape(ingress(), quote=True) + '">Startseite</a></div>')
    return back, tabs


def more_page(ingress):
    return '<section class="card"><h1>Mehr</h1><div class="more-grid">' + ''.join(
        '<a class="btn light" href="' + escape(ingress(path), quote=True) + '">' + label + '</a>'
        for path, label in MORE) + '</div></section>'
