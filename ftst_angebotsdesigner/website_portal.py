"""Revision-bound customer portal. No Billomat writes or outbound message sends."""
import hashlib
import hmac
import json
import os
import logging
import threading
import re
from pathlib import Path
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from uuid import uuid4
from urllib.parse import urlsplit

from flask import abort, redirect, request, send_file
from materials import account
from billomat_client import BillomatClient
from offer_mail import csrf, form_identity
from website_portal_client import PortalClient, PortalError

KIND = 'website_portal_offer'
CENT = Decimal('.01')


def amount(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0 or d > Decimal('99999999.99'):
            raise ValueError
        return d.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError('Ungültiger oder negativer Betrag.') from None


def money(value):
    return format(amount(value), '.2f')


def configured():
    return os.getenv('WEBSITE_PORTAL_ENABLED', '').lower() == 'true'


def client():
    if not configured():
        raise ValueError('Kundenportal ist noch nicht eingerichtet.')
    return PortalClient(os.getenv('WEBSITE_PORTAL_URL', ''),
                        os.getenv('WEBSITE_PORTAL_SECRET', ''),
                        site_service_token=os.getenv('WEBSITE_PORTAL_SITE_TOKEN') or None)


def fingerprint(offer):
    # Only frozen commercial and public presentation fields, never account secrets.
    public = {k: offer.get(k) for k in ('id', 'status', 'is_draft', 'date', 'validity_date',
              'validity_days', 'offer_number', 'number', 'customer_title', 'customer_intro',
              'project_summary', 'items', 'total_net', 'total_gross', 'tax_amount', 'client', 'reference_image_ids', 'reference_images', 'company_profile')}
    return hashlib.sha256(json.dumps(public, sort_keys=True, ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def attach(store, identity, offer):
    result = dict(offer)
    if not configured(): return result
    saved = store.record(identity, KIND, str(offer['id']))
    if saved and not saved.get('revoked') and saved['source_digest'] == fingerprint(offer):
        try:
            valid = datetime.fromisoformat(saved['link']['expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc)
        except (ValueError, KeyError):
            valid = False
        if valid:
            result['customer_portal_url'] = saved['link']['customer_url']
    return result


def category(title):
    t = title.lower()
    if any(x in t for x in ('montage', 'inbetriebnahme', 'home assistant', 'home-assistant', 'software')):
        return 'service'
    if any(x in t for x in ('kamera', 'camera', 'turret', 'bullet', 'dome')): return 'camera'
    if any(x in t for x in ('curtain outdoor', 'curtainoutdoor', 'dualcurtain', 'perimeter', 'außenschutz', 'aussenschutz')): return 'perimeter'
    if any(x in t for x in ('outdoor', 'aussen', 'außen')) and any(x in t for x in ('motion', 'bewegung')): return 'outdoor_motion'
    if any(x in t for x in ('streetsiren', 'außensirene', 'aussensirene')): return 'outdoor_siren'
    if 'hub' in t: return 'hub'
    if any(x in t for x in ('doorprotect', 'öffnung')): return 'contact'
    if any(x in t for x in ('motion', 'bewegung')): return 'motion'
    if any(x in t for x in ('siren', 'sirene')): return 'siren'
    if any(x in t for x in ('keypad', 'tastatur')): return 'keypad'
    return 'other'


def snapshot(offer, revision, editable_ids=(), extra_articles=()):
    if offer.get('is_draft') or offer.get('status') == 'DRAFT':
        raise ValueError('Entwürfe können nicht veröffentlicht werden.')
    if offer.get('currency_code', 'EUR') != 'EUR':
        raise ValueError('Das Portal unterstützt EUR.')
    today = date.today()
    try:
        issued = date.fromisoformat(str(offer.get('date') or today))
        valid = date.fromisoformat(str(offer['validity_date'])) if offer.get('validity_date') else issued + timedelta(days=int(offer.get('validity_days') or 30))
    except (ValueError, TypeError):
        raise ValueError('Ausstellungsdatum und Gültigkeit prüfen.') from None
    if valid < today:
        raise ValueError('Der Leistungsvorschlag ist nicht mehr gültig.')
    lines, net, tax = [], Decimal(0), Decimal(0)
    for n, item in enumerate(offer.get('items') or [], 1):
        quantity = Decimal(str(item['quantity']))
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError('Mengen müssen positiv sein.')
        line_net = amount(item['total_net'])
        unit = amount(item['unit_price'])
        line_id = 'position-' + str(n)
        cat = category(item.get('title', ''))
        # Commercial discounts are already included in the effective unit.
        effective = amount(line_net / quantity)
        exact = amount(effective * quantity) == line_net
        optional = cat == 'service' and any(x in item.get('title', '').lower() for x in ('home assistant', 'home-assistant', 'software'))
        editable = line_id in editable_ids and exact and quantity == int(quantity) and quantity <= 50
        if line_id in editable_ids and not editable:
            raise ValueError('Diese Position kann nicht centgenau zur Auswahl freigegeben werden.')
        if cat == 'service' and not optional: editable = False
        if optional and editable and quantity != 1:
            raise ValueError('Optionale Leistung muss eine Pauschale mit Menge 1 sein.')
        rate = str(item.get('tax_rate') or '19')
        if Decimal(rate) != 19:
            raise ValueError('Diese Integration unterstützt geprüfte 19%-Positionen.')
        line_tax = amount(line_net * Decimal('.19'))
        options = [{'id': 'original', 'title': item.get('title') or 'Leistung',
                    'description': (item.get('description') or '')[:2000], 'manufacturer': '',
                    'supplier_sku': '', 'variant': '', 'color': '',
                    'effective_unit_net': money(effective)}] if editable else []
        photo = product_image(item.get('title', ''))
        if editable and photo: options[0]['product_image_id'] = photo
        lines.append(dict(id=line_id, title=item.get('title') or 'Leistung',
                          description=item.get('description') or '', quantity=str(int(quantity)) if editable else str(quantity),
                          unit=('Pauschale' if cat == 'service' else item.get('unit') or 'Stück'),
                          unit_net=money(unit), line_net=money(line_net), tax_rate='19',
                          line_tax=money(line_tax), editable=editable,
                          min_quantity=1 if cat == 'hub' and editable else 0,
                          max_quantity=1 if optional else 50,
                          selected_option='original' if editable else None,
                          options=options, visual_category=cat,
                          **({'optional_service': True} if optional and editable else {})))
        net += line_net
        tax += line_tax
    if not lines or len(lines) > 30 or net != amount(offer['total_net']) or net + tax != amount(offer['total_gross']):
        raise ValueError('Positionssummen, Rabatt oder Steuer weichen ab. Keine Veröffentlichung.')
    for article in extra_articles:
        aid = str(article['id'])
        title = article['title']
        options = [dict(id='original', title=title, description=(article.get('description') or '')[:2000],
                        manufacturer='Ajax', supplier_sku='', variant='', color='',
                        effective_unit_net=money(article['sales_price']))]
        photo = product_image(title)
        if photo: options[0]['product_image_id'] = photo
        lines.append(dict(id='article-' + aid, title=title, description=article.get('description') or '',
                          quantity='0', unit=article['unit'], unit_net=money(article['sales_price']),
                          line_net='0.00', tax_rate='19', line_tax='0.00', editable=True,
                          min_quantity=0, max_quantity=20, selected_option='original', options=options,
                          visual_category=category(title)))
    if len(lines) > 30: raise ValueError('Höchstens 30 freigegebene Positionen.')
    c = offer.get('client') or {}
    display = c.get('company') or c.get('name') or ' '.join(str(c.get(k) or '') for k in ('first_name', 'last_name')).strip() or 'Kunde'
    address = ', '.join(str(c.get(k) or '') for k in ('street', 'zip', 'city')).strip(', ')
    return dict(schema_version='ftst.customer-proposal.v1', document_id='billomat-' + hashlib.sha256(os.getenv('BILLOMAT_ID', '').strip().lower().encode()).hexdigest()[:16] + '-' + str(offer['id']),
                revision=revision, number=str(offer.get('offer_number') or offer.get('number') or offer['id']),
                issued_at=issued.isoformat(), valid_until=valid.isoformat(), approved_for_customer=True,
                title=offer.get('customer_title') or offer.get('title') or 'Ihr Sicherheitsprojekt',
                intro=offer.get('customer_intro') or '', customer_display=display, object_address=address,
                company=dict(name='FT Sicherheitstechnik', contact='Hafenbahnstraße 15, 68305 Mannheim',
                             email='info@ftst.eu', phone='+49 621 159 647 34'),
                project_summary=offer.get('project_summary') or '', currency='EUR', price_source='BILLOMAT',
                catalog_at=today.isoformat(), lines=lines, totals=dict(net=money(net), tax=money(tax), gross=money(net + tax)),
                images=[], phases=[])




def product_image(title):
    # Exact advertised model/colour only. Similar models must not share a guessed photo.
    t = re.sub(r'[^a-z0-9]+', '', title.lower().replace('weiß', 'weiss'))
    white = any(c in t for c in ('white', 'weiss'))
    black = any(c in t for c in ('black', 'schwarz'))
    if white == black: return None
    if white and 'turretcam' in t and '8mp' in t and '28' in t:
        return 'ax-turretcam-8mp-2.8-w'
    if white and 'motionprotectoutdoor' in t and 'motioncam' not in t:
        return 'ax-motion-protect-outdoor-w'
    if white and 'dualcurtainoutdoor' in t:
        return 'ax-dual-curtain-outdoor-w'
    suffix = 'w' if white else 'b'
    if 'streetsiren' in t and 'doubledeck' not in t:
        return 'ax-street-siren-' + suffix
    if any(x in t for x in ('outdoor', 'fibra', 'superior', 'motioncam', 'hub2g', 'hub4g')): return None
    exact = [('hub2plus', 'hub-2-plus'), ('hub24g', 'hub-2-4g'),
             ('doorprotectplus', 'door-protect-plus'), ('doorprotect', 'door-protect'),
             ('motionprotectplus', 'motion-protect-plus'), ('motionprotect', 'motion-protect'),
             ('homesiren', 'home-siren'), ('keypadplus', 'keypad-plus'), ('keypad', 'keypad')]
    for model, asset in exact:
        if model in t: return 'ax-' + asset + '-' + suffix
    return None


def approved_images(offer):
    # Exactly the pictures selected for the customer PDF, not the whole account gallery.
    descriptors, payload = [], {}
    for n, image in enumerate(offer.get('reference_images', [])[:4], 1):
        image_id = 'reference-' + str(n)
        data = Path(image['path']).read_bytes()
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Freigegebenes Bild überschreitet 2 MB; zuvor verkleinern.')
        if not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff')):
            raise ValueError('Freigegebenes Bild benötigt PNG/JPEG.')
        descriptors.append(dict(id=image_id, caption=image.get('title') or 'Freigegebenes Referenzbild',
                                role='reference', kind='reference'))
        payload[image_id] = data
    return descriptors, payload

def additional_catalog(raw):
    if raw.get('settings', {}).get('net_gross') != 'NET' or raw.get('settings', {}).get('currency_code') != 'EUR':
        raise ValueError('Zusatzartikel benötigen Billomat-Netto-EUR-Preise.')
    units = {str(u['id']): u.get('name') for u in raw['units']}
    result = {}
    for article in raw['articles']:
        title = str(article.get('title') or '')
        if 'ajax' not in title.lower() or category(title) not in ('camera', 'outdoor_motion', 'perimeter', 'outdoor_siren'):
            continue
        aid = str(article.get('id'))
        if not aid.isascii() or not aid.isdigit() or not units.get(str(article.get('unit_id'))): continue
        if (article.get('currency_code') or 'EUR') != 'EUR': continue
        if article.get('sales_price') in (None, ''): continue
        price = money(article['sales_price'])
        result[aid] = dict(id=aid, title=title, description=article.get('description') or '',
                           sales_price=price, unit=units[str(article['unit_id'])])
    return result


def read_catalog():
    return additional_catalog(BillomatClient(os.getenv('BILLOMAT_ID'),
                                            os.getenv('BILLOMAT_API_KEY')).draft_catalog())

def accepted_configuration(saved, response):
    s = saved['snapshot']
    if (response.get('kind') != 'approval' or response.get('status') != 'customer_confirmed'
            or response.get('confirmed') is not True or response.get('revision') != s['revision']
            or response.get('document_id') != s['document_id']):
        raise ValueError('Keine bestätigte Konfiguration dieser Revision.')
    choices = response.get('selections', [])
    if not isinstance(choices, list) or len(choices) != sum(l['editable'] for l in s['lines']):
        raise ValueError('Auswahl ist unvollständig.')
    selected = {c['line_id']: c for c in choices}
    if len(selected) != len(choices): raise ValueError('Doppelte Auswahl.')
    items, net, tax = [], Decimal(0), Decimal(0)
    for n, line in enumerate(s['lines'], 1):
        title, desc, qty, unit = line['title'], line['description'], line['quantity'], line['unit_net']
        line_net = amount(line['line_net'])
        if line['editable']:
            choice = selected.pop(line['id'], None)
            if not choice: raise ValueError('Auswahl fehlt.')
            option = next((o for o in line['options'] if o['id'] == choice.get('option_id')), None)
            q = choice.get('quantity')
            if (not option or not isinstance(q, str) or not q.isascii() or not q.isdigit()
                    or not line['min_quantity'] <= int(q) <= line['max_quantity']):
                raise ValueError('Nicht freigegebene Variante oder Menge.')
            title, desc, qty, unit = option['title'], option['description'], q, option['effective_unit_net']
            line_net = amount(Decimal(unit) * Decimal(q))
        net += line_net
        tax += amount(line_net * Decimal(line['tax_rate']) / 100)
        if Decimal(qty) > 0:
            items.append(dict(position=len(items) + 1, title=title, description=desc, quantity=qty,
                              unit=line['unit'], unit_price=unit, total_net=money(line_net), optional=0, reduction=''))
    if selected: raise ValueError('Unbekannte Position.')
    totals = dict(net=money(net), tax=money(tax), gross=money(net + tax))
    if response.get('preview_totals') != totals or response.get('final_totals') != totals: raise ValueError('Bestätigte Summen weichen ab.')
    # Never copy caller-provided prices, titles or arbitrary source properties.
    return dict(id=uuid4().hex, source_document_id=s['document_id'], source_revision=s['revision'],
                response_id=response['request_id'], status='customer_confirmed', items=items, totals=totals,
                customer_display=s['customer_display'], title=s['title'], signature=response.get('signature'),
                confirmed_at=response.get('created_at'))


def register(app, base, ingress, clean, get_store, get_offer, make_pdf):
    def check_post():
        if not hmac.compare_digest(request.form.get('csrf', '').encode(), csrf().encode()) or request.form.get('account') != account():
            abort(400, 'Formularsitzung abgelaufen.')

    @app.route('/offer/<oid>/portal', methods=['GET', 'POST'])
    def offer_portal(oid):
        store, identity = get_store(), account()
        offer = get_offer(oid)
        if request.method == 'POST':
            check_post()
            if request.form.get('action') == 'revoke':
                saved = store.record(identity, KIND, oid)
                if not saved: abort(404)
                client().revoke(saved['link']['link_id'])
                store.put_record(identity, KIND, oid, dict(saved, revoked=True))
                return redirect(ingress('offer/' + oid + '/portal'))
            if request.form.get('approved') != 'yes': abort(400, 'Freigabe fehlt.')
            previous = store.record(identity, KIND, oid) or {}
            if request.form.get('digest') != fingerprint(offer): abort(409, 'Angebot geändert. Neu prüfen.')
            try:
                extra_ids = list(dict.fromkeys(request.form.getlist('extra_article')))
                catalog = read_catalog() if extra_ids else {}
                if any(aid not in catalog for aid in extra_ids):
                    raise ValueError('Zusatzartikel ist nicht freigegeben.')
                s = snapshot(offer, int(previous.get('snapshot', {}).get('revision', 0)) + 1, request.form.getlist('editable'), [catalog[aid] for aid in extra_ids])
                pdf = make_pdf(offer).getvalue()
                s['images'], image_bytes = approved_images(offer)
                remote = client().publish(s, pdf, image_bytes)
                link = client().create_link(remote['proposal_id'])
                # Validate returned URLs against configured portal origin.
                if (urlsplit(link['customer_url']).scheme != 'https'
                        or urlsplit(link['customer_url']).netloc != urlsplit(os.getenv('WEBSITE_PORTAL_URL')).netloc
                        or urlsplit(link['customer_url']).path != '/angebot/' + remote['proposal_id']
                        or not re.fullmatch(r'[A-Za-z0-9_-]{43}', urlsplit(link['customer_url']).fragment)):
                    raise ValueError('Unerwarteter Kundenlink.')
                saved = dict(snapshot=s, source_digest=fingerprint(offer), original_offer=offer,
                             proposal_id=remote['proposal_id'], link=link, revoked=False)
                store.put_record(identity, 'website_portal_revision', remote['proposal_id'], saved)
                store.put_record(identity, KIND, oid, saved)
            except (PortalError, ValueError):
                abort(502, 'Portal konnte nicht vorbereitet werden. Zugang, Gültigkeit und centgenaue Preise prüfen. Kein Versand.')
            return redirect(ingress('offer/' + oid))
        saved = store.record(identity, KIND, oid)
        rows = ''.join('<label><input type="checkbox" name="editable" value="position-' + str(n) + '"> ' + clean(i.get('title', 'Leistung')) + '</label><br>' for n, i in enumerate(offer.get('items', []), 1))
        try:
            extra = read_catalog() if configured() else {}
        except Exception:
            extra = {}
        rows += '<h2>Optionale Ajax-Erweiterungen</h2><p>Ausgewählte Zusatzartikel starten mit Menge 0. Der Kunde kann sie zum freigegebenen Billomat-Verkaufspreis netto plus 19 % hinzufügen.</p>'
        rows += ''.join('<label><input type="checkbox" name="extra_article" value="' + clean(aid) + '"> ' + clean(article['title']) + ' · ' + clean(article['sales_price']) + ' EUR netto</label><br>' for aid, article in extra.items())
        if not extra: rows += '<p>Kein passender Netto-EUR-Katalog verfügbar. Billomat-Katalog prüfen.</p>'
        existing = ('<p><a href="' + clean(saved['link']['customer_url']) + '" rel="noreferrer">Persönlichen Kundenlink öffnen</a></p>') if saved and not saved.get('revoked') else ''
        body = '<section class="card"><h1>Persönlicher Kundenlink</h1><p>Nur geprüfte Positionen freigeben. Der Kunde kann ausgewählte Mengen selbst ändern und zum berechneten Endpreis bestätigen. Montage bleibt fest.</p>'
        body += existing + '<form method="post">' + form_identity() + '<input type="hidden" name="digest" value="' + fingerprint(offer) + '">' + rows + '<label><input type="checkbox" name="approved" value="yes" required> Darstellung, Preise und Auswahlgrenzen für den Kunden freigegeben</label><p><button class="btn">Link vorbereiten</button></p></form>'
        if saved and not saved.get('revoked'):
            body += '<form method="post">' + form_identity() + '<button class="btn light" name="action" value="revoke">Kundenlink widerrufen</button></form>'
        return base('Kundenportal', body + '</section>')

    @app.post('/portal/sync')
    def portal_sync():
        check_post()
        try:
            synchronize(get_store(), account(), make_pdf)
        except (PortalError, ValueError, KeyError, TypeError, OSError):
            abort(502, 'Portalantworten konnten nicht sicher übernommen werden. Cursor bleibt erhalten.')
        return redirect(ingress('portal/responses'))

    @app.get('/portal/responses')
    def portal_responses():
        store, identity = get_store(), account()
        rows = ''
        for key, value in store.records(identity, 'website_portal_response').items():
            accepted = store.record(identity, 'website_portal_accepted', key)
            rows += '<li>' + clean(value.get('kind')) + ': ' + clean(value.get('message', ''))
            if accepted:
                rows += ' · ' + clean(accepted['totals']['gross']) + ' EUR <a href="' + ingress('portal/accepted/' + key + '/pdf') + '">Bestätigte Auswahl als PDF</a>'
            rows += '</li>'
        return base('Kundenantworten', '<section class="card"><h1>Kundenantworten</h1><form method="post" action="' + ingress('portal/sync') + '">' + form_identity() + '<button class="btn">Antworten abrufen</button></form><ul>' + rows + '</ul></section>')

    @app.get('/portal/accepted/<key>/pdf')
    def accepted_pdf(key):
        store, identity = get_store(), account()
        accepted = store.record(identity, 'website_portal_accepted', key)
        if not accepted: abort(404)
        response = store.record(identity, 'website_portal_response', key)
        saved = store.record(identity, 'website_portal_revision', response['proposal_id'])
        return send_file(final_pdf(store, saved, accepted, make_pdf), mimetype='application/pdf',
                         download_name='FTST-Bestaetigte-Auswahl.pdf')


def final_pdf(store, saved, accepted, make_pdf):
    # Retain exact bytes for transport retries; ReportLab creation metadata varies.
    path = Path(store.directory) / 'portal-pdfs' / (accepted['id'] + '.pdf')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        offer = deepcopy(saved['original_offer'])
        offer.update(items=accepted['items'], total_net=accepted['totals']['net'],
                     total_gross=accepted['totals']['gross'], tax_amount=accepted['totals']['tax'],
                     taxes=[{'amount': accepted['totals']['tax']}],
                     project_summary='Bestätigte Kundenauswahl: ' + '; '.join(str(i['quantity']) + ' × ' + i['title'] for i in accepted['items']),
                     customer_title=accepted['title'] + ' – bestätigte Kundenauswahl', is_draft=False)
        data = make_pdf(offer).getvalue()
        temporary = path.parent / (uuid4().hex + '.tmp')
        try:
            with open(temporary, 'xb') as target:
                os.chmod(temporary, 0o600)
                target.write(data)
                target.flush()
                os.fsync(target.fileno())
            # Exclusive creation prevents concurrent readers seeing partial writes.
            try: os.link(temporary, path)
            except FileExistsError: pass
        finally:
            temporary.unlink(missing_ok=True)
    return path


_sync_lock = threading.Lock()


def synchronize(store, identity, make_pdf, transport=None):
    with _sync_lock:
        transport = transport or client()
        state = store.record(identity, 'website_portal_cursor', 'current') or {'after': 0}
        result = transport.responses(state['after'])
        for response in result['responses']:
            saved = store.record(identity, 'website_portal_revision', response['proposal_id'])
            if not saved: continue
            key = response['request_id']
            if store.record(identity, 'website_portal_response', key): continue
            if response['kind'] == 'approval':
                accepted = store.record(identity, 'website_portal_accepted', key)
                if not accepted:
                    accepted = accepted_configuration(saved, response)
                    store.put_record(identity, 'website_portal_accepted', key, accepted)
                pdf = final_pdf(store, saved, accepted, make_pdf).read_bytes()
                transport.publish_final_pdf(response['proposal_id'], key, pdf)
            store.put_record(identity, 'website_portal_response', key, response)
        store.put_record(identity, 'website_portal_cursor', 'current', {'after': result['next_cursor']})


def start_sync(get_store, make_pdf):
    if not configured(): return
    identity = os.getenv('BILLOMAT_ID', '').strip().lower()
    if not identity: return
    def run():
        interval = threading.Event()
        while True:
            try: synchronize(get_store(), identity, make_pdf)
            except Exception:
                logging.getLogger('ftst.portal').warning('Kundenportal-Abgleich fehlgeschlagen; keine Daten überschrieben.')
            interval.wait(60)
    threading.Thread(target=run, name='ftst-portal-sync', daemon=True).start()
