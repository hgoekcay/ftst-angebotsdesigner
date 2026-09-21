"""Reviewable local quote drafts; explicit transfer is a separate workflow."""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import abort, redirect, request, send_file
from billomat_client import BillomatClient
from materials import account
from storage import StorageError, RecordConflict


def number(value, maximum='100000000'):
    try:
        result = Decimal(str(value).strip().replace(',', '.'))
        if not result.is_finite() or result < 0 or result > Decimal(maximum):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValueError('Ungültige Zahl oder Betrag außerhalb des erlaubten Bereichs.') from None


def rounded(value):
    return str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def display_money(value):
    return f'{Decimal(value):,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def fingerprint(project):
    return hashlib.sha256(json.dumps({k: project.get(k) for k in ('notes', 'analysis', 'image', 'audio')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def components(project):
    analysis = project.get('analysis', {}).get('components')
    if analysis:
        if len(analysis) > 100:
            raise ValueError('Bitte höchstens 100 Positionen verwenden.')
        return [{'description': str(x.get('description', ''))[:300], 'quantity': str(x['quantity']) if x.get('quantity') is not None else '', 'evidence': str(x.get('evidence', ''))[:500]} for x in analysis]
    # Only a quantity at the beginning is extracted. Other prose remains visible.
    result = []
    for line in re.split(r'\n|;|\s+\+\s+|\s+und\s+', project.get('notes', '')):
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(?:[x×]\s*|(?:Stück|stk\.?|Stunden|Std\.?)\s+)?(.+)', line, re.I)
        result.append({'description': (match[2] if match else line)[:300], 'quantity': match[1] if match else '', 'evidence':line[:500]})
    if len(result) > 100:
        raise ValueError('Bitte höchstens 100 Positionen verwenden.')
    return result


def tokens(value):
    return set(re.findall(r'[\w]+', str(value).casefold()))


def candidates(description, articles):
    # Quantity and connecting prose must not suggest unrelated products.
    ignored = {'mit', 'und', 'für', 'fur', 'eine', 'einen', 'einem', 'einer', 'der', 'die', 'das', 'von', 'stk', 'stück', 'ajax'}
    # The intake's visible room annotation is installation context, not a
    # product term. Keep it on the requirement, but out of article matching.
    description = description.partition(' · Raum / Montageort: ')[0]
    terms = tokens(description)
    wanted = {word for word in terms if not word.isdigit() and word not in ignored}
    # These are search synonyms only. BM/MK require the explicitly confirmed
    # Ajax context; product variants still require a manual article selection.
    families = set()
    if 'ajax' in terms:
        if 'bm' in terms or any(word.startswith('bewegungsmeld') for word in terms):
            families.update(('motionprotect', 'motioncam'))
        if 'mk' in terms or any(word.startswith('magnetkontakt') for word in terms):
            families.add('doorprotect')
        if any(word.startswith('sirene') or word.startswith(('innensirene', 'aussensirene')) for word in terms):
            families.update(('homesiren', 'streetsiren'))
        if any(word.startswith(('bedienteil', 'aussenbedienteil', 'innenbedienteil')) for word in terms):
            families.add('keypad')
        if any(word.startswith(('zentrale', 'alarmzentrale')) for word in terms):
            families.add('hub')
    outside = any(word.startswith(('aussen', 'outdoor')) for word in terms)
    inside = any(word.startswith(('innen', 'indoor')) for word in terms)
    locations = {'aussen', 'aussenbereich', 'aussenmontage', 'outdoor', 'innen', 'innenbereich', 'innenmontage', 'indoor'}
    accessories = ('halter', 'halterung', 'montageplatte', 'batterie', 'abdeckung', 'blende', 'hood')
    ranked = []
    for article in articles:
        title = tokens(article.get('title', ''))
        score = sum(2 if word in title else 1 if any(
            len(word) >= 4 and len(term) >= 4 and (word.startswith(term) or term.startswith(word))
            for term in title) else 0 for word in wanted)
        exact_number = bool(article.get('article_number')) and str(article['article_number']).casefold() == description.casefold()
        if families and not exact_number:
            family_match = any(term.startswith(family) for term in title for family in families)
            # A location or the brand name alone must not make an unrelated
            # Ajax product appear as a detector, siren or keypad suggestion.
            device_words = wanted - {'bm', 'mk'} - locations
            title_devices = title - locations
            named_device = any(word in title_devices or any(len(word) >= 4 and len(term) >= 4
                               and (word.startswith(term) or term.startswith(word)) for term in title_devices)
                               for word in device_words)
            if not family_match and not ('ajax' in title and named_device):
                continue
            accessory = any(term.startswith(prefix) for term in title for prefix in accessories)
            requested_accessory = any(word.startswith(prefix) for word in terms for prefix in accessories)
            if accessory and not requested_accessory:
                continue
            if 'hub' in families:
                # Compatibility mentions such as "ReX für Hub" or "Netzteil
                # für Hub" do not turn a repeater/accessory into a central unit.
                extra = ('rex', 'repeater', 'netzteil', 'psu', 'zubehör', 'zubehoer')
                requested_extra = {prefix for prefix in extra if any(word.startswith(prefix) for word in terms)}
                article_extra = {prefix for prefix in extra if any(word.startswith(prefix) for word in title)}
                if article_extra and not article_extra.intersection(requested_extra):
                    continue
            article_outside = any(term.startswith(('aussen', 'outdoor', 'streetsiren')) for term in title)
            article_inside = any(term.startswith(('innen', 'indoor', 'homesiren')) for term in title)
            if outside != inside:
                if (outside and article_inside and not article_outside) or (inside and article_outside and not article_inside):
                    continue
                if (outside and article_outside) or (inside and article_inside):
                    score += 3
            if family_match:
                score += 6
        if exact_number:
            score += 100
        if score:
            ranked.append((score, article))
    return [a for _, a in sorted(ranked, key=lambda pair: (-pair[0], str(pair[1].get('title', '')), str(pair[1]['id'])))[:30]]


def catalog_snapshot(raw):
    fields = {
        'articles': ('id','article_number','title','description','sales_price','sales_price2','sales_price3','sales_price4','sales_price5','currency_code','unit_id','tax_id','type'),
        'clients': ('id','client_number','name','first_name','last_name','price_group','reduction','tax_rule','net_gross','currency_code','archived'),
        'taxes': ('id','name','rate','is_default'),
        'units': ('id','name'),
    }
    result = {kind:[{k:r.get(k) for k in keys} for r in raw[kind]] for kind,keys in fields.items()}
    result['settings'] = {k:raw['settings'].get(k) for k in ('currency_code','net_gross')}
    return result


def calculate(draft):
    catalog = draft.get('catalog', {})
    clients = {str(c['id']):c for c in catalog.get('clients', [])}
    client = clients.get(draft.get('client_id'))
    problems, lines = [], []
    if not client or str(client.get('archived')) == '1':
        return {'problems':['Bitte einen aktiven Billomat-Kunden auswählen.'], 'lines':[], 'total':None}
    settings = catalog['settings']
    currency = client.get('currency_code') or settings.get('currency_code')
    basis = settings.get('net_gross')
    # Do not infer how Billomat converts article prices for a different customer basis.
    customer_basis = client.get('net_gross')
    if basis != 'NET' or customer_basis not in ('NET', 'SETTINGS', None, ''):
        problems.append('Bruttopreisbasis oder unbekannte Preisbasis: Kalkulation in Billomat prüfen.')
    if not currency:
        problems.append('Währung fehlt.')
    tax_rule = client.get('tax_rule')
    if tax_rule not in ('TAX', 'NO_TAX', 'COUNTRY'):
        problems.append('Unbekannte oder fehlende Steuerregel: Kundendaten in Billomat prüfen.')
    elif tax_rule == 'COUNTRY' and draft.get('tax_confirmed') != 'yes':
        problems.append('Länderabhängige Steuerregel: Anwendung der Artikelsteuersätze bitte fachlich bestätigen.')
    if problems:
        for index, row in enumerate(draft.get('rows', []), 1):
            if not row.get('article_id'):
                problems.append(f'Position {index}: Artikel auswählen.')
        if not draft.get('rows'):
            problems.append('Mindestens eine Position ergänzen.')
        return {'problems':problems, 'lines':[], 'total':None, 'currency':currency}
    try:
        group = str(client.get('price_group') or '1')
        if group not in ('1','2','3','4','5'):
            raise ValueError('Unbekannte Kundenpreisgruppe.')
        reduction = number(client.get('reduction') or '0', '100')
    except ValueError as exc:
        return {'problems':[str(exc)], 'lines':[], 'total':None}
    articles = {str(a['id']):a for a in catalog['articles']}
    taxes = {str(t['id']):t for t in catalog['taxes']}
    units = {str(u['id']):u.get('name') for u in catalog['units']}
    defaults = [t for t in catalog['taxes'] if str(t.get('is_default')) == '1']
    net, tax = Decimal(0), Decimal(0)
    for index, row in enumerate(draft.get('rows', []), 1):
        try:
            article = articles.get(row.get('article_id'))
            if not article:
                raise ValueError('Artikel auswählen.')
            quantity = number(row.get('quantity'), '1000000')
            if quantity == 0:
                raise ValueError('Menge muss größer als null sein.')
            if (article.get('currency_code') or settings.get('currency_code')) != currency:
                raise ValueError('Abweichende Artikelwährung; kein automatischer Wechselkurs.')
            field = 'sales_price' if group == '1' else 'sales_price'+group
            if article.get(field) in (None, ''):
                field = 'sales_price'
            price = number(article.get(field))
            if not units.get(str(article.get('unit_id'))):
                raise ValueError('Einheit fehlt; bitte den Artikel in Billomat vervollständigen.')
            selected_tax = taxes.get(str(article.get('tax_id')))
            if not selected_tax and article.get('tax_id') in (None, '', 0, '0') and len(defaults) == 1:
                selected_tax = defaults[0]
            if tax_rule == 'NO_TAX':
                rate = Decimal(0)
            elif selected_tax:
                rate = number(selected_tax.get('rate'), '100')
            else:
                raise ValueError('Steuersatz fehlt oder ist mehrdeutig.')
            amount = Decimal(rounded(quantity * price * (1 - reduction / 100)))
            line_tax = Decimal(rounded(amount * rate / 100))
            net += amount
            tax += line_tax
            lines.append(dict(title=article.get('title'), article_number=article.get('article_number'), quantity=str(quantity), unit=units.get(str(article.get('unit_id'))) or 'Einheit offen', price=str(price), price_field=field, net=str(amount), tax_rate=str(rate)))
        except ValueError as exc:
            problems.append(f'Position {index}: {exc}')
    if not draft.get('rows'):
        problems.append('Mindestens eine Position ergänzen.')
    return dict(problems=problems, lines=lines, total=None if problems else dict(net=rounded(net), tax=rounded(tax), gross=rounded(net+tax)), currency=currency, reduction=str(reduction), group=group)


def register(app, base, ingress, escape, get_store):
    @app.get('/projects/<key>/quote/pdf')
    def quote_pdf(key):
        store = get_store()
        identity = account()
        project = store.record(identity, 'project', key)
        draft = store.record(identity, 'quote', key)
        if project is None or draft is None:
            abort(404)
        if not draft.get('revision') or request.args.get('revision') != draft['revision']:
            abort(409, 'Der Entwurf wurde geändert. Bitte den aktuellen Stand neu öffnen.')
        result = calculate(draft)
        if draft.get('source') != fingerprint(project) or not draft.get('reviewed') or result['total'] is None:
            abort(409, 'Bitte aktuelle Anforderungen, Positionen und Kalkulation zuerst vollständig prüfen und speichern.')
        from quote_export import build
        try:
            document = build(dict(project, id=key), draft, result, store)
        except ValueError as exc:
            abort(409, str(exc))
        # A concurrent edit must not silently produce an obsolete review document.
        current_project = store.record(identity, 'project', key)
        current_draft = store.record(identity, 'quote', key)
        if current_project != project or current_draft != draft:
            abort(409, 'Die Daten wurden während des Exports geändert. Bitte neu laden.')
        response = send_file(document, mimetype='application/pdf', as_attachment=False,
                             download_name='FTST-Angebotsentwurf.pdf')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/projects/<key>/quote', methods=['GET','POST'])
    def quote_draft(key):
        store = get_store()
        project = store.record(account(), 'project', key)
        if project is None:
            abort(404)
        draft = store.record(account(), 'quote', key)
        if draft is None:
            try:
                draft = {'rows':components(project), 'source':fingerprint(project), 'revision':'', 'client_id':''}
            except ValueError as exc:
                abort(400, str(exc))
        notice = ''
        if not draft.get('catalog'):
            shared = store.record(account(), 'catalog', 'shared') or {}
            if shared.get('data'):
                draft['catalog'] = shared['data']
                draft['catalog_at'] = shared['at']
        status = 200
        if request.method == 'POST':
            if request.form.get('revision', '') != draft['revision']:
                abort(409, 'Der Entwurf wurde inzwischen geändert. Bitte neu laden.')
            action = request.form.get('action')
            try:
                if action == 'catalog':
                    bid, api_key = os.getenv('BILLOMAT_ID'), os.getenv('BILLOMAT_API_KEY')
                    if not bid or not api_key:
                        raise ValueError('Billomat ist noch nicht eingerichtet.')
                    draft['catalog'] = catalog_snapshot(BillomatClient(bid, api_key).draft_catalog())
                    draft['catalog_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                    store.put_record(account(), 'catalog', 'shared', dict(data=draft['catalog'], at=draft['catalog_at']))
                elif action == 'source':
                    draft['rows'] = components(project)
                    draft['source'] = fingerprint(project)
                elif action == 'save':
                    rows = []
                    descriptions = request.form.getlist('description')
                    quantities = request.form.getlist('quantity')
                    ids = request.form.getlist('article_id')
                    if len(descriptions) > 101 or len({len(descriptions),len(quantities),len(ids)}) != 1:
                        abort(400)
                    for description, quantity, aid in zip(descriptions, quantities, ids):
                        if not description.strip() and not quantity.strip() and not aid:
                            continue
                        rows.append(dict(description=description[:300], quantity=quantity[:30], article_id=aid[:30]))
                    if len(rows) > 100:
                        raise ValueError('Bitte höchstens 100 Positionen verwenden.')
                    draft['rows'] = rows
                    changed_client = draft.get('client_id') != request.form.get('client_id', '')[:30]
                    draft['client_id'] = request.form.get('client_id', '')[:30]
                    draft['tax_confirmed'] = '' if changed_client else request.form.get('tax_confirmed', '')
                    draft['reviewed'] = request.form.get('reviewed') == 'yes'
                else:
                    abort(400)
                if action != 'save':
                    draft['reviewed'] = False
                    draft['tax_confirmed'] = ''
                draft['revision'] = uuid.uuid4().hex
                store.put_revision(account(), 'quote', key, draft, request.form.get('revision', ''))
                return redirect(ingress('projects/'+key+'/quote')+'?saved=1')
            except RecordConflict as exc:
                abort(409, str(exc))
            except StorageError:
                raise
            except RuntimeError:
                notice, status = 'Billomat-Daten konnten nicht vollständig geladen werden. Der gespeicherte Entwurf bleibt erhalten.', 503
            except ValueError as exc:
                notice, status = str(exc), 400
        stale = draft['source'] != fingerprint(project)
        result = calculate(draft)
        if stale:
            result['problems'].append('Projektnotizen wurden geändert. Entwurf mit den aktuellen Anforderungen abgleichen.')
            result['total'] = None
        catalog = draft.get('catalog', {})
        articles = catalog.get('articles', [])
        def option(value, label, selected):
            return f'<option value="{escape(value)}" {"selected" if str(value)==str(selected) else ""}>{escape(label)}</option>'
        customer_options = option('', 'Bitte auswählen', draft.get('client_id'))
        for c in catalog.get('clients', []):
            if str(c.get('archived')) != '1':
                label = ' · '.join(str(c[k]) for k in ('client_number','name','first_name','last_name') if c.get(k)) or str(c['id'])
                customer_options += option(c['id'], label, draft.get('client_id'))
        rows = ''
        for index, row in enumerate(draft['rows']+[{'description':'','quantity':''}]):
            matches = candidates(row['description'], articles)
            selected = next((a for a in articles if str(a['id'])==row.get('article_id')), None)
            if selected and selected not in matches:
                matches.insert(0, selected)
            opts = option('', 'Artikel auswählen / Suche speichern', row.get('article_id'))
            opts += ''.join(option(a['id'], str(a.get('article_number') or '')+' · '+str(a.get('title') or ''), row.get('article_id')) for a in matches)
            rows += f'<tr><td><label for="desc{index}">Anforderung / Artikelsuche</label><input id="desc{index}" name="description" value="{escape(row["description"])}"></td><td><label for="qty{index}">Menge</label><input id="qty{index}" name="quantity" inputmode="decimal" value="{escape(row["quantity"])}"></td><td><label for="article{index}">Billomat-Artikel</label><select id="article{index}" name="article_id">{opts}</select></td></tr>'
        problems = ''.join(f'<li>{escape(p)}</li>' for p in result['problems'])
        preview = ''.join(f'<tr><td data-label="Artikel">{escape(x["article_number"])} · {escape(x["title"])}</td><td data-label="Menge">{escape(x["quantity"])} {escape(x["unit"])}</td><td data-label="Einzelpreis netto" class="money">{display_money(x["price"])} {escape(result.get("currency"))}</td><td data-label="Steuer">{escape(x["tax_rate"])} %</td><td data-label="Nach Rabatt netto" class="money">{display_money(x["net"])} {escape(result.get("currency"))}</td></tr>' for x in result['lines'])
        total = result['total']
        totals = f'<div class="success">Entwurf: Netto {display_money(total["net"])} · Steuer {display_money(total["tax"])} · Brutto {display_money(total["gross"])} {escape(result.get("currency"))}</div>' if total else '<p>Gesamtsumme offen, bis alle Angaben eindeutig sind.</p>'
        revision = f'<input type="hidden" name="revision" value="{escape(draft["revision"])}">'
        export = '<p>PDF-Entwurf verfügbar, sobald alle Angaben geprüft und gespeichert sind.</p>'
        if total is not None and draft.get('reviewed') and draft.get('revision'):
            export = f'<p><a class="btn dark" data-pdf="FTST-Angebotsentwurf.pdf" href="{ingress("projects/"+key+"/quote/pdf")}?revision={escape(draft["revision"])}">PDF-Entwurf öffnen</a></p><p class="muted">Zur internen Prüfung; noch keine Freigabe und kein Versand.</p>'
        saved = '<p class="success">Entwurf gespeichert.</p>' if request.args.get('saved') else ''
        guide = ('<section class="card"><h2>Von der Aufnahme zum Angebot</h2>'
                 '<ol><li>Artikel und Kunden aus Billomat laden, falls der Katalog noch fehlt.</li>'
                 '<li>Den richtigen Billomat-Kunden auswählen und jeder Position einen konkreten Artikel zuordnen.</li>'
                 '<li>Mengen, Montage, Anfahrt, Zubehör und Kundenkonditionen prüfen und speichern.</li>'
                 '<li>Den PDF-Entwurf prüfen. Danach ist die gesonderte Übergabe an Billomat möglich.</li></ol>')
        if project.get('customer_name'):
            guide += f'<p><strong>Kunde laut Aufnahme:</strong> {escape(project["customer_name"])}</p>'
        guide += '<p>Ein Kundenname aus der Aufnahme ist noch keine Billomat-Zuordnung. Fehlende Kundendaten können Sie ergänzen; ohne passenden Kunden und vollständige Artikelzuordnung bleibt die Summe offen.</p>'
        if stale:
            guide += ('<p role="alert"><strong>Die Aufnahme wurde geändert.</strong> Die bisherige Kalkulation bleibt erhalten. '
                      'Mit „Positionen aus aktuellen Notizen neu übernehmen“ ersetzen Sie deren Positionsliste durch die aktuellen Anforderungen; '
                      'bisherige Artikelzuordnungen müssen danach erneut geprüft werden.</p>')
        if result['problems']:
            guide += '<h3>Aktuell noch zu erledigen</h3><ul>' + problems + '</ul>'
        guide += '</section>'
        presentation_link = f'<p><a class="btn light" href="{ingress("projects/"+key+"/quote/presentation")}">Kundentexte & Fotos gestalten</a></p>'
        if not draft.get('revision'):
            presentation_link = '<p>Kundentexte und Fotos können nach dem ersten Speichern gestaltet werden.</p>'
        body = f'''<div class="back"><a href="{ingress('projects/'+key)}">← Projekt</a></div><div class="card"><h1>Angebotsentwurf: {escape(project['title'])}</h1>{saved}{presentation_link}<p>{escape(notice)}</p><p>Lokaler Entwurf zur Prüfung. In Billomat wird noch kein Angebot angelegt.</p><p>Notizen: {escape(project.get('notes'))}</p><form method="post">{revision}<button class="btn" name="action" value="catalog">Artikel und Kunden aus Billomat laden</button><button class="btn light" name="action" value="source">Positionen aus aktuellen Notizen neu übernehmen</button></form><p>Speichern sichert Ihre Auswahl. Der Knopf „Artikel und Kunden aus Billomat laden“ aktualisiert die Stammdaten.</p><p><a href="{ingress("customers")}" target="_blank" rel="noopener">Kunden suchen oder neu anlegen</a></p><p>{len(draft.get("catalog",{}).get("articles",[]))} Artikel · {len(draft.get("catalog",{}).get("clients",[]))} Kunden geladen</p><p>Datenstand (UTC): {escape(draft.get('catalog_at') or 'Noch nicht geladen')}</p></div>
        <div class="card"><form method="post">{revision}<label for="client">Billomat-Kunde</label><select id="client" name="client_id">{customer_options}</select><p>Suchtext oder Menge ändern und speichern. Danach den passenden Artikel auswählen. Die letzte leere Zeile ergänzt eine Position; eine vollständig geleerte Zeile wird entfernt.</p><table>{rows}</table><p><label><input style="width:auto" type="checkbox" name="tax_confirmed" value="yes" {'checked' if draft.get('tax_confirmed')=='yes' else ''}> Bei länderabhängiger Steuerregel: Die Artikelsteuersätze gelten für diesen Auftrag.</label></p><p><label><input style="width:auto" type="checkbox" name="reviewed" value="yes" {'checked' if draft.get('reviewed') else ''}> Varianten, Mengen, Montage, Anfahrt und Zubehör geprüft.</label></p><button class="btn" name="action" value="save">Auswahl und Mengen speichern</button></form></div>
        <div class="card"><h2>Kalkulation zur Prüfung</h2><ul>{problems}</ul><p>Preisgruppe: {escape(result.get('group'))} · Kundenrabatt: {escape(result.get('reduction'))} %. Skonto ist nicht abgezogen.</p><table><tr><th>Artikel</th><th>Menge</th><th>Einzelpreis netto</th><th>Steuer</th><th>Nach Rabatt netto</th></tr>{preview}</table>{totals}<p>{'Leistungsumfang als geprüft markiert.' if draft.get('reviewed') else 'Leistungsumfang noch prüfen: Montage, Anfahrt und Zubehör werden nicht automatisch ergänzt.'}</p><p>Rundung je Position; abschließende Summenprüfung erfolgt bei der späteren Übernahme in Billomat.</p></div>'''
        transfer = store.record(account(), 'quote_transfer', key)
        if transfer:
            body = body.replace('<p>Lokaler Entwurf zur Prüfung. In Billomat wird noch kein Angebot angelegt.</p>',
                                '<p>Für dieses Projekt besteht ein Billomat-Übertragungsvorgang. Den aktuellen Stand finden Sie unter „Billomat-Übertragung öffnen“.</p>', 1)
        transfer_label = 'Billomat-Übertragung öffnen' if transfer else 'Übergabe an Billomat prüfen'
        transfer_link = f'<p><a class="btn" href="{ingress("projects/"+key+"/quote/transfer")}">{transfer_label}</a></p>'
        return base('Angebotsentwurf', guide + body + '<div class="card">' + export + transfer_link + '</div>'), status
