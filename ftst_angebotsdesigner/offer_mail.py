"""Reviewed, frozen MIME messages with account-bound, at-most-once SMTP submission."""
import base64
import hashlib
import hmac
import io
import json
import re
import secrets
import time
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from html import escape
from uuid import uuid4

from flask import abort, redirect, request, session, Response
from PIL import Image, ImageOps

from asset_library import catalog
from materials import account
from offer_delivery import messages
from storage import RecordConflict
import offer_smtp

KIND = 'offer_mail_delivery'
MAX_PDF = 15 * 1024 * 1024
MAX_EML = 24 * 1024 * 1024
STATUS = {'prepared': 'Vorbereitet – noch nicht versendet',
          'sending': 'Versand läuft oder Ergebnis noch ungeklärt – nicht erneut senden',
          'accepted': 'Vom Mailserver angenommen – Zustellung nicht bestätigt',
          'failed': 'Nicht versendet – Mailserver oder Zugang prüfen',
          'uncertain': 'Versandergebnis unklar – vor erneutem Versand beim Empfänger prüfen'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate(values):
    recipient = values.get('recipient', '').strip()
    subject = values.get('subject', '').strip()
    text = values.get('text', '').strip()
    if (len(recipient) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", recipient)
            or any(x in recipient for x in '\r\n,;')):
        raise ValueError('Bitte genau eine gültige E-Mail-Adresse eintragen.')
    if not subject or len(subject) > 200 or any(ord(c) < 32 for c in subject):
        raise ValueError('Bitte einen Betreff ohne Zeilenumbruch mit höchstens 200 Zeichen eintragen.')
    if not text or len(text) > 4000 or '\x00' in text:
        raise ValueError('Bitte einen Nachrichtentext mit höchstens 4000 Zeichen eintragen.')
    return recipient, subject, text


def picture(item):
    with Image.open(item['path']) as source:
        image = ImageOps.exif_transpose(source)
        if item.get('logo_crop'):
            x, y, width, height = item['logo_crop']
            image = image.crop((x, y, x + width, y + height))
        image = image.convert('RGB')
        image.thumbnail((960, 260))
        result = io.BytesIO()
        image.save(result, format='PNG')
        return result.getvalue()


def references(store, identity):
    assets = catalog(store, identity)
    saved = store.record(identity, 'profile', 'email_references') or {}
    result = []
    for entry in saved.get('items', [])[:3]:
        if entry.get('id') in assets and entry.get('label'):
            result.append((entry['label'], assets[entry['id']]))
    return result


def build_message(offer, recipient, subject, text, pdf, refs):
    if not pdf.startswith(b'%PDF-') or len(pdf) > MAX_PDF:
        raise ValueError('Die PDF fehlt, ist ungültig oder größer als 15 MB.')
    msg = EmailMessage(policy=policy.SMTP)
    msg['From'] = 'FT Sicherheitstechnik <' + offer_smtp.SENDER + '>'
    msg['To'] = recipient
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=False)
    msg['Message-ID'] = make_msgid(domain='ftst.eu')
    msg['Reply-To'] = offer_smtp.SENDER
    msg.set_content(text)
    images = []
    logo = ''
    if offer.get('logo_path'):
        data = picture({'path': offer['logo_path'], 'logo_crop': offer.get('logo_crop')})
        images.append(('ftst-logo', data))
        logo = '<img src="cid:ftst-logo" alt="FT Sicherheitstechnik ®" width="340" style="max-width:100%;height:auto">'
    cards = ''
    for index, (label, item) in enumerate(refs):
        cid = 'reference-' + str(index)
        images.append((cid, picture(item)))
        cards += ('<td style="padding:12px 6px;width:33%;vertical-align:top;text-align:center">'
                  '<img src="cid:' + cid + '" alt="' + escape(label, quote=True) + '" width="145" style="max-width:100%;height:auto">'
                  '<p style="font-size:12px;color:#555;overflow-wrap:anywhere">' + escape(label) + '</p></td>')
    paragraphs = ''.join('<p style="margin:0 0 18px;line-height:1.6;overflow-wrap:anywhere">' +
                         escape(part).replace('\n', '<br>') + '</p>' for part in text.split('\n\n'))
    reference_html = ('<h2 style="font-size:17px;margin-top:28px">Ausgewählte Kundenreferenzen</h2>'
                      '<table role="presentation" width="100%"><tr>' + cards + '</tr></table>') if cards else ''
    html = ('<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
            '<body style="margin:0;background:#f3f5f4;font-family:Arial,sans-serif;color:#202020">'
            '<table role="presentation" width="100%"><tr><td style="padding:20px 12px">'
            '<table role="presentation" width="100%" style="max-width:640px;margin:auto;background:#fff;border-top:5px solid #16803c">'
            '<tr><td style="padding:28px 24px">' + logo +
            '<h1 style="font-size:24px;line-height:1.3;margin:28px 0">Ihr persönlicher Leistungsvorschlag</h1>' + paragraphs +
            '<p><a href="https://tidycal.com/ftsicherheit/erstberatung" style="display:inline-block;background:#16803c;color:white;'
            'text-decoration:none;padding:14px 20px;border-radius:6px">Beratungstermin buchen</a></p>' + reference_html +
            '</td></tr></table></td></tr></table></body></html>')
    msg.add_alternative(html, subtype='html')
    html_part = msg.get_payload()[-1]
    for cid, data in images:
        html_part.add_related(data, maintype='image', subtype='png', cid='<' + cid + '>', disposition='inline')
    filename = 'FTST-Leistungsvorschlag-' + re.sub(r'[^A-Za-z0-9_-]', '-', str(offer['id'])) + '.pdf'
    msg.add_attachment(pdf, maintype='application', subtype='pdf', filename=filename)
    raw = msg.as_bytes()
    if len(raw) > MAX_EML:
        raise ValueError('Die Nachricht ist zu groß. Bitte die PDF-Bilder verkleinern.')
    return raw, str(msg['Message-ID'])


def freeze(store, identity, oid, values, offer, pdf):
    recipient, subject, text = validate(values)
    raw, message_id = build_message(offer, recipient, subject, text, pdf, references(store, identity))
    digest = hashlib.sha256(raw).hexdigest()
    key = uuid4().hex
    record = dict(id=key, offer_id=oid, recipient=recipient, subject=subject, text=text,
                  created_at=now(), created_epoch=time.time(), status='prepared', digest=digest,
                  message_id=message_id, sender=offer_smtp.SENDER)
    def create(current, db):
        if current:
            raise RecordConflict('Diese Nachricht existiert bereits.')
        db.execute('INSERT OR IGNORE INTO mail_blobs(account,hash,data) VALUES(?,?,?)', (identity, digest, raw))
        return record
    store.transact_record(identity, KIND, key, create)
    return record


def submit(store, identity, key):
    if not offer_smtp.configured():
        raise ValueError('Direktversand noch nicht eingerichtet. Bitte die E-Mail-Einstellungen öffnen.')
    def claim(value, _db):
        if not value or value.get('status') != 'prepared':
            raise RecordConflict('Diese Nachricht wurde bereits bearbeitet. Der Versand wird nicht wiederholt.')
        if time.time() - value['created_epoch'] > 3600:
            raise ValueError('Diese Vorschau ist älter als eine Stunde. Bitte eine neue Vorschau erstellen.')
        return dict(value, status='sending', attempted_at=now())
    record = store.transact_record(identity, KIND, key, claim)
    raw = store.mail_blob(identity, record['digest'])
    if not raw or hashlib.sha256(raw).hexdigest() != record['digest']:
        outcome = 'failed'
    else:
        outcome = offer_smtp.deliver(record['recipient'], raw)
    return store.transact_record(identity, KIND, key, lambda value, _db: dict(value, status=outcome, finished_at=now()))


def register(app, base, ingress, clean, get_store, get_offer, make_pdf):
    def csrf():
        return session.setdefault('offer_mail_csrf', secrets.token_urlsafe(32))

    def check_post():
        if (not hmac.compare_digest(request.form.get('csrf', '').encode(), csrf().encode())
                or request.form.get('account') != account()):
            abort(400, 'Formularsitzung abgelaufen. Bitte die Seite neu öffnen.')

    def hidden():
        return '<input type="hidden" name="csrf" value="' + clean(csrf()) + '"><input type="hidden" name="account" value="' + clean(account()) + '">'

    def page(title, content, code=200):
        response = app.make_response((base(title, content), code))
        response.headers['Cache-Control'] = 'no-store'
        return response

    def load_offer(oid):
        if not re.fullmatch(r'[1-9][0-9]{0,17}', oid):
            abort(404)
        try:
            offer = get_offer(oid)
        except Exception:
            abort(502, 'Billomat konnte nicht geprüft werden. Bitte später erneut versuchen.')
        if str(offer.get('id')) != oid:
            abort(404)
        if offer.get('is_draft'):
            abort(409, 'Entwürfe dürfen noch nicht an Kunden versendet werden.')
        return offer

    def load_record(key):
        if not re.fullmatch(r'[a-f0-9]{32}', key):
            abort(404)
        result = get_store().record(account(), KIND, key)
        if not result:
            abort(404)
        return result

    @app.route('/offer/<oid>/email', methods=['GET', 'POST'])
    def offer_email(oid):
        if request.method == 'POST':
            check_post()
        offer = load_offer(oid)
        subject, text, _ = messages(offer)
        customer = offer.get('client') or {}
        values = request.form if request.method == 'POST' else dict(
            recipient=customer.get('email') or customer.get('email_address') or '', subject=subject, text=text)
        error = ''
        if request.method == 'POST':
            try:
                validate(values)
                record = freeze(get_store(), account(), oid, values, offer, make_pdf(offer).getvalue())
                return redirect(ingress('email-delivery/' + record['id']), code=303)
            except (ValueError, OSError):
                error = 'Bitte gültige Empfängeradresse, Betreff und Text prüfen. Die PDF und Bilder müssen verfügbar sein (PDF maximal 15 MB).'
        history = [v for v in get_store().records(account(), KIND).values() if v.get('offer_id') == oid][:10]
        rows = ''.join('<li><a href="' + ingress('email-delivery/' + x['id']) + '">' + clean(x['created_at']) +
                       ' · ' + clean(x['recipient']) + '</a><br>' + clean(STATUS.get(x['status'], x['status'])) + '</li>' for x in history)
        body = '<div class="card"><h1>Leistungsvorschlag per E-Mail</h1><p>Absender: FT Sicherheitstechnik · info@ftst.eu</p>'
        if not offer_smtp.configured():
            body += '<p>Direktversand noch nicht eingerichtet. Vorschau und EML-Datei können Sie bereits vorbereiten.</p>'
        body += ('<p role="alert">' + clean(error) + '</p><form method="post">' + hidden() +
                 '<label for="mail-recipient">E-Mail des Kunden</label><input id="mail-recipient" name="recipient" type="email" required maxlength="254" value="' + clean(values.get('recipient', '')) + '">'
                 '<label for="mail-subject">Betreff</label><input id="mail-subject" name="subject" required maxlength="200" value="' + clean(values.get('subject', '')) + '">'
                 '<label for="mail-text">E-Mail-Text einschließlich Signatur</label><textarea id="mail-text" name="text" required maxlength="4000" style="min-height:360px">' + clean(values.get('text', '')) + '</textarea>'
                 '<p>Die Vorschau enthält die aktuelle PDF, das FT-Logo und die hinterlegten Kundenlogos. Es wird noch nichts versendet.</p>'
                 '<button class="btn" style="background:#16803c">E-Mail mit PDF prüfen</button></form>'
                 '<p><a href="' + ingress('email-settings') + '">Mailzugang & Referenzlogos</a> · <a href="' + ingress('offer/' + oid) + '">Zurück zum Leistungsvorschlag</a></p></div>'
                 '<div class="card"><h2>Versandverlauf</h2><ul>' + rows + '</ul><p>Zeitangaben in UTC. Eine Serverannahme ist keine Empfangsbestätigung. Unklare Vorgänge nicht erneut versenden.</p></div>')
        return page('E-Mail vorbereiten', body, 400 if error else 200)

    @app.route('/email-delivery/<key>', methods=['GET', 'POST'])
    def email_delivery(key):
        record = load_record(key)
        error = ''
        if request.method == 'POST':
            check_post()
            if request.form.get('confirm') != 'yes':
                abort(400, 'Bitte Empfänger, Nachricht und PDF prüfen und bestätigen.')
            # Fresh status blocks withdrawn/draft offers, while the attachment remains the reviewed snapshot.
            load_offer(record['offer_id'])
            try:
                submit(get_store(), account(), key)
            except (ValueError, RecordConflict) as exc:
                error = str(exc)
            record = load_record(key)
        path = 'email-delivery/' + key
        body = ('<div class="card"><h1>E-Mail prüfen & senden</h1><p><b>Von:</b> FT Sicherheitstechnik · info@ftst.eu<br>'
                '<b>An:</b> ' + clean(record['recipient']) + '<br><b>Betreff:</b> ' + clean(record['subject']) + '</p><p role="status">' +
                clean(STATUS[record['status']]) + '</p><p role="alert">' + clean(error) + '</p>'
                '<a class="btn light" href="' + ingress(path + '/pdf') + '">Genauen PDF-Anhang prüfen</a>'
                '<a class="btn light" href="' + ingress(path + '/eml') + '">E-Mail-Datei herunterladen</a>'
                '<iframe title="E-Mail-Vorschau" sandbox="" style="display:block;width:100%;height:780px;border:1px solid #ddd;margin:20px 0" src="' + ingress(path + '/preview') + '"></iframe>')
        if record['status'] == 'prepared':
            if offer_smtp.configured():
                body += ('<form method="post">' + hidden() + '<label><input type="checkbox" name="confirm" value="yes" required> Empfänger, E-Mail und PDF geprüft</label>'
                         '<p>Die unten stehende Aktion verschickt diese E-Mail mit dem geprüften PDF-Anhang.</p>'
                         '<button class="btn" style="background:#16803c">Jetzt per E-Mail senden</button></form>')
            else:
                body += '<p>Direktversand noch nicht eingerichtet. Unter <a href="' + ingress('email-settings') + '">Mailzugang & Referenzlogos</a> finden Sie die nächsten Schritte.</p>'
        body += ('<p>Die Vorschau bleibt eine Stunde sendefähig. Änderungen am Leistungsvorschlag erfordern eine neue Vorschau. Gespeicherte Nachrichten werden nicht automatisch erneut versendet.</p>'
                 '<a href="' + ingress('offer/' + record['offer_id'] + '/email') + '">Zur E-Mail-Vorbereitung</a> · '
                 '<a href="' + ingress('offer/' + record['offer_id'] + '/followup') + '">Wiedervorlage festlegen</a></div>')
        return page('E-Mail prüfen', body, 409 if error else 200)

    @app.get('/email-delivery/<key>/<part>')
    def email_delivery_file(key, part):
        record = load_record(key)
        raw = get_store().mail_blob(account(), record['digest'])
        if not raw or hashlib.sha256(raw).hexdigest() != record['digest']:
            abort(404)
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        if part == 'preview':
            html = msg.get_body(preferencelist=('html',)).get_content()
            # Old frozen messages lack an HTML charset. Ingress/proxies may strip
            # the HTTP charset, so the preview must also declare it in-document.
            if not re.search(r'<meta\s+charset=', html, re.IGNORECASE):
                html = html.replace('<head>', '<head><meta charset="utf-8">', 1)
            for image in msg.walk():
                cid = str(image.get('Content-ID', '')).strip('<>')
                if cid and image.get_content_type() == 'image/png':
                    html = html.replace('cid:' + cid + '"', 'data:image/png;base64,' + base64.b64encode(image.get_payload(decode=True)).decode() + '"')
            response = Response(html, mimetype='text/html')
            response.headers['Content-Security-Policy'] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; frame-ancestors 'self'; sandbox"
        elif part == 'pdf':
            attachment = next(x for x in msg.iter_attachments() if x.get_content_type() == 'application/pdf')
            response = Response(attachment.get_payload(decode=True), mimetype='application/pdf')
            response.headers['Content-Disposition'] = 'inline; filename="Leistungsvorschlag.pdf"'
        elif part == 'eml':
            response = Response(raw, mimetype='message/rfc822')
            response.headers['Content-Disposition'] = 'attachment; filename="Leistungsvorschlag.eml"'
        else:
            abort(404)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.route('/email-settings', methods=['GET', 'POST'])
    def email_settings():
        store, identity = get_store(), account()
        assets = catalog(store, identity)
        notice = ''
        saved = store.record(identity, 'profile', 'email_references') or {}
        items = saved.get('items', [])
        if request.method == 'POST':
            check_post()
            if request.form.get('action') == 'check':
                notice = ('SMTP-Anmeldung erfolgreich. Es wurde keine Nachricht versendet.' if offer_smtp.check() else
                          'SMTP-Anmeldung nicht möglich. Aktivierung und Postfachpasswort in den App-Optionen prüfen. Es wurde nichts versendet.')
            elif request.form.get('action') == 'references':
                items = []
                for i in range(3):
                    key = request.form.get('image_' + str(i), '')
                    label = request.form.get('label_' + str(i), '').strip()
                    if key:
                        if key not in assets or assets[key].get('bundled') or not label or len(label) > 100:
                            abort(400, 'Bitte ein hochgeladenes Logo und eine Kunden-/Standortbezeichnung mit höchstens 100 Zeichen auswählen.')
                        if key in [x['id'] for x in items]:
                            abort(400, 'Jedes Logo bitte nur einmal auswählen.')
                        items.append({'id': key, 'label': label})
                store.put_record(identity, 'profile', 'email_references', {'items': items})
                notice = 'Referenzleiste gespeichert. Bereits vorbereitete E-Mails bleiben unverändert.'
            else:
                abort(400)
        body = ('<div class="card"><h1>Mailzugang & Referenzlogos</h1><p role="status">' + clean(notice) + '</p>'
                '<h2>Direktversand von info@ftst.eu</h2><p>' + ('Aktiviert und Zugang hinterlegt.' if offer_smtp.configured() else 'Noch nicht eingerichtet.') + '</p>'
                '<p>Home Assistant → Apps → FTST AngebotsDesigner → Konfiguration: strato_smtp_enabled aktivieren. '
                'Für strato_smtp_password das Postfachpasswort von info@ftst.eu hinterlegen. Ein bereits vorhandenes Passwort des direkten STRATO-Abrufs wird verwendet, wenn das SMTP-Feld leer bleibt.</p>'
                '<p>Die Verbindung ist verschlüsselt. Der Anmeldetest versendet keine E-Mail. Gesendete Nachrichten und Anhänge bleiben im Versandverlauf dieser App; eine Kopie im STRATO-Ordner „Gesendet“ wird nicht angelegt.</p>'
                '<form method="post">' + hidden() + '<button class="btn light" name="action" value="check">SMTP-Anmeldung prüfen</button></form></div>'
                '<div class="card"><h2>Bis zu drei Kundenlogos</h2><p>Originale unter <a href="' + ingress('materials') + '">Bilder</a> hochladen, hier auswählen und den tatsächlichen Kunden oder Standort nennen. Leere Plätze erscheinen nicht in der E-Mail.</p>'
                '<form method="post">' + hidden())
        for i in range(3):
            item = items[i] if i < len(items) else {}
            options = '<option value="">Kein Logo</option>'
            for key, asset in assets.items():
                if not asset.get('bundled'):
                    options += '<option value="' + clean(key) + '"' + (' selected' if key == item.get('id') else '') + '>' + clean(asset.get('title', key)) + '</option>'
            body += ('<label for="image_' + str(i) + '">Referenzlogo ' + str(i + 1) + '</label><select id="image_' + str(i) + '" name="image_' + str(i) + '">' + options + '</select>'
                     '<label for="label_' + str(i) + '">Kunde / Standort</label><input id="label_' + str(i) + '" name="label_' + str(i) + '" maxlength="100" value="' + clean(item.get('label', '')) + '">')
        body += '<p><button class="btn" style="background:#16803c" name="action" value="references">Referenzleiste speichern</button></p></form></div>'
        return page('Mailzugang & Referenzlogos', body)

