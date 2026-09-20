"""Read-only guidance through the saved project, quote and transfer states."""
from html import escape

from project_intake import fingerprint as intake_fingerprint
from quote_drafts import calculate, fingerprint


def progress(project, intake=None, draft=None, transfer=None):
    """Describe persisted evidence only; never refresh or change external data."""
    intake, draft, transfer = intake or {}, draft or {}, transfer or {}
    analysis = project.get('analysis') or {}
    steps = [
        dict(title='Aufnahme', state='Offen', text='Komponenten, Mengen und Einbauorte erfassen.',
             path='intake', action='Technikeraufnahme öffnen'),
        dict(title='Artikel & Preise', state='Offen', text='Kunde und passende Billomat-Artikel auswählen.',
             path='quote', action='Kalkulation öffnen'),
        dict(title='Kundentexte & Fotos', state='Vorbereiten', text='Texte und bis zu vier Referenzbilder in der PDF prüfen.',
             path='quote', action='Zuerst Kalkulation speichern'),
        dict(title='Billomat-Entwurf', state='Noch nicht übertragen',
             text='Geprüften Entwurf nach Vorschau ausdrücklich übernehmen.',
             path='quote/transfer', action='Übergabe prüfen'),
    ]
    first, calculation, design, delivery = steps
    has_input = bool(str(project.get('notes') or '').strip() or analysis.get('components')
                     or project.get('image') or project.get('audio'))
    if intake:
        first.update(state='Gespeichert · bitte prüfen', text='Die Aufnahme ist gespeichert; die Übernahme ins Projekt steht noch aus.')
        if intake.get('status') == 'analyzing':
            first.update(state='Fotoauswertung prüfen', text='Fotoauswertung und Ergebnis in der Technikeraufnahme öffnen.')
        elif (intake.get('status') == 'applied' and not intake.get('review_required')
              and not intake.get('source_changed') and analysis.get('user_confirmed')):
            first.update(state='Angaben übernommen', text='Bestätigte Komponenten wurden in das Projekt übernommen.')
            if intake.get('source_project') != intake_fingerprint(project):
                first['text'] += ' Das Projekt wurde danach geändert; Angaben bei Bedarf abgleichen.'
        elif intake.get('components'):
            first['text'] = 'Komponenten und Mengen prüfen und ins Projekt übernehmen.'
    elif has_input:
        first.update(state='Eingaben vorhanden', text='Notizen oder Anhänge sind vorhanden. Anforderungen und Mengen prüfen.')

    questions = [str(q).strip() for q in (intake.get('questions') or analysis.get('questions') or []) if str(q).strip()]
    if questions:
        first['text'] += f' {len(questions)} offene Rückfrage(n) sind gespeichert.'

    ready = False
    if draft.get('revision'):
        design.update(state='Auswahl verfügbar', path='quote/presentation', action='Texte & Fotos öffnen')
        calculation.update(state='Gespeichert · bitte prüfen', text='Artikel, Mengen, Kundenkonditionen und Leistungsumfang prüfen.')
        if draft.get('source') != fingerprint(project):
            calculation.update(state='Anforderungen geändert', text='Die Kalkulation mit den aktuellen Projektangaben abgleichen.')
        else:
            try:
                result = calculate(draft)
                ready = bool(draft.get('reviewed') and result.get('total') is not None and not result.get('problems'))
            except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
                result = {'problems': ['Gespeicherten Katalog und Kundendaten erneut prüfen.']}
            if ready:
                calculation.update(state='Lokal geprüft', text='Kalkulation und Leistungsumfang sind geprüft. Billomat-Daten werden vor der Übergabe erneut abgeglichen.')
            elif result.get('problems'):
                calculation['text'] = ' '.join(str(p) for p in result['problems'][:3])

    next_index = 1 if has_input else 0
    if intake and first['state'] != 'Angaben übernommen':
        next_index = 0
    if ready and not (intake and first['state'] != 'Angaben übernommen'):
        next_index = 3
    if transfer:
        next_index = 3
        delivery.update(state='Status prüfen', text='Eine Übertragung besteht bereits. Den gespeicherten Vorgang prüfen.',
                        action='Billomat-Status prüfen')
        if transfer.get('status') == 'created':
            delivery.update(state='Entwurf angelegt', text='Der übertragene Stand wurde aus Billomat zurückgelesen und geprüft. Freigabe und Versand erfolgen separat.',
                            action='Übertragung öffnen')
            if transfer.get('draft') != draft or (transfer.get('project') and fingerprint(transfer['project']) != fingerprint(project)):
                delivery.update(state='Früherer Stand übertragen', text='Der lokale Projekt- oder Kalkulationsstand wurde geändert. Die bestehende Übertragung prüfen; es wird kein zweites Angebot angelegt.')
        elif transfer.get('status') == 'sending':
            delivery['text'] = 'Der Vorgang wurde begonnen. Bei unterbrochener Verbindung den Status prüfen.'
        elif transfer.get('status') in ('unknown', 'review'):
            delivery['text'] = 'Das Ergebnis ist noch nicht eindeutig bestätigt. Über den bestehenden Vorgang den Status in Billomat prüfen.'
    elif project.get('offer_id'):
        next_index = 3
        delivery.update(state='Angebot verknüpft', text='Ein Billomat-Angebot ist verknüpft. Sein aktueller Status wird beim Öffnen angezeigt.',
                        path='', action='Verknüpftes Angebot öffnen', offer_id=str(project['offer_id']))
    elif not ready:
        delivery.update(path='quote', action='Zuerst Kalkulation prüfen')
    return dict(steps=steps, next_index=next_index, questions=questions)


def render(project, key, store, identity, ingress):
    state = progress(project, store.record(identity, 'project_intake', key),
                     store.record(identity, 'quote', key), store.record(identity, 'quote_transfer', key))

    def url(step):
        path = 'offer/' + step['offer_id'] if step.get('offer_id') else 'projects/' + key + '/' + step['path']
        return escape(ingress(path), quote=True)

    next_step = state['steps'][state['next_index']]
    body = '<section class="card project-workflow" aria-labelledby="workflow-title"><h2 id="workflow-title">Ihr Weg zum Angebot</h2>'
    body += '<p class="muted">Stand der gespeicherten Angaben. Jeder Schritt bleibt einzeln prüfbar.</p>'
    body += f'<p><strong>Nächster Schritt: {escape(next_step["action"])}</strong></p><a class="btn" href="{url(next_step)}">{escape(next_step["action"])}</a>'
    body += '<ol class="workflow-steps">'
    for step in state['steps']:
        body += (f'<li><strong>{escape(step["title"])}</strong><span class="workflow-state">{escape(step["state"])}</span>'
                 f'<p>{escape(step["text"])}</p><a href="{url(step)}">{escape(step["action"])}</a></li>')
    body += '</ol>'
    if state['questions']:
        body += '<details><summary>Offene Rückfragen anzeigen</summary><ul>'
        body += ''.join('<li>' + escape(q) + '</li>' for q in state['questions']) + '</ul></details>'
    body += '</section><style>.workflow-steps{padding-left:24px}.workflow-steps>li{padding:16px 0;border-bottom:1px solid #e2e5e7}.workflow-state{display:block;color:#606970;font-size:14px;margin-top:5px}.workflow-steps p{margin:8px 0}.workflow-steps a{display:inline-block;padding:8px 0;min-height:28px}.project-workflow a{overflow-wrap:anywhere}</style>'
    return body
