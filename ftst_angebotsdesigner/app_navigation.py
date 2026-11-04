"""Persistent app navigation with local, deterministic return destinations."""
from html import escape

from flask import current_app, request
from werkzeug.exceptions import HTTPException

SECTIONS = [('offers', 'Angebote', '<path d="M6 3h9l3 3v15H6zM9 9h6M9 13h6M9 17h4"/>'),
            ('projects', 'Projekte', '<path d="M3 7h7l2-3h9v16H3z"/>'),
            ('customers', 'Kunden', '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>'),
            ('more', 'Mehr', '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>')]
MORE = [('chat', 'KI-Assistent'), ('intake-templates', 'Aufnahmebögen'),
        ('inventory', 'Lager'), ('materials', 'Bilder'), ('company', 'Firma'),
        ('mail', 'Antwortassistent'), ('email-settings', 'E-Mail-Einstellungen'),
        ('portal/responses', 'Kundenantworten'), ('billomat', 'Billomat'), ('ai', 'Lokale KI')]


def navigation(ingress):
    path = request.path.strip('/')
    group = path.split('/')[0]
    active = {'offer': 'offers', 'project': 'projects', 'customer': 'customers',
              'email-delivery': 'offers'}.get(group, group)
    if active not in ('offers', 'projects', 'customers'):
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
