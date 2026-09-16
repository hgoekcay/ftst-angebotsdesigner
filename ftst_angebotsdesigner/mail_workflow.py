"""Bounded manual EML intake. No mailbox transport, rendering or attachment execution."""
import hashlib
import re
import uuid
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
from email import policy
from email.parser import BytesParser

MAX_EML = 8 * 1024 * 1024
CATEGORIES = {
    'enquiry': 'Kundenanfrage', 'service': 'Service / Störung', 'order': 'Laufender Auftrag',
    'invoice': 'Rechnung / Gutschrift', 'purchase': 'Einkauf / Lieferung', 'general': 'Allgemein',
}
STATUSES = {'new': 'Neu', 'review': 'Zu prüfen', 'ready': 'Bereit zur Freigabe',
            'waiting': 'Wartet auf Antwort', 'done': 'Erledigt'}
DOCUMENTS = {'none': 'Kein Beleg zugeordnet', 'invoice': 'Rechnung', 'credit': 'Gutschrift', 'reminder': 'Mahnung'}
DOC_STATES = {'review': 'Angaben prüfen', 'assigned': 'Zugeordnet', 'ready': 'Bereit zur Übergabe',
              'exported': 'Export bestätigt', 'handed': 'Übergabe bestätigt', 'booked': 'Buchung bestätigt'}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def safe_name(value):
    return re.sub(r'[\x00-\x1f\x7f/\\]', '_', str(value))[:160] or 'Anhang.bin'


def parse_eml(raw):
    if not raw or len(raw) > MAX_EML:
        raise ValueError('Bitte eine EML-Datei bis maximal 8 MiB importieren.')
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        if not any(msg.get(x) for x in ('From', 'Subject', 'Date', 'Message-ID')):
            raise ValueError('Keine erkennbare E-Mail. Das Original wurde nicht importiert.')
        original = hashlib.sha256(raw).hexdigest()
        blobs = {original: raw}
        attachments, texts, warnings = [], [], []
        count = 0

        def visit(part, depth=0):
            nonlocal count
            count += 1
            if count > 100 or depth > 20:
                raise ValueError('Diese MIME-Struktur überschreitet das Importlimit (100 Teile / 20 Ebenen).')
            mime = part.get_content_type()
            attached = part.get_content_disposition() == 'attachment' or part.get_filename()
            if part.is_multipart() and not attached and mime != 'message/rfc822':
                for child in part.iter_parts():
                    visit(child, depth + 1)
                return
            data = part.get_payload(decode=True)
            if data is None:
                # Preserve forwarded/multipart attachments without treating their body as the current request.
                data = part.as_bytes(policy=policy.default)
            if mime == 'text/plain' and not attached:
                try:
                    texts.append(data.decode(part.get_content_charset() or 'ascii', errors='strict'))
                except (UnicodeError, LookupError):
                    warnings.append('Ein Textteil konnte nicht verlustfrei dekodiert werden; bitte Original prüfen.')
                    attached = True
            else:
                attached = True
            if part.defects:
                warnings.append('MIME-Abweichung erkannt; Darstellung mit dem Original abgleichen.')
            if attached:
                digest = hashlib.sha256(data).hexdigest()
                blobs[digest] = data
                attachments.append({'hash': digest, 'name': safe_name(part.get_filename() or 'Ungeprüfter-' + mime.replace('/', '-') + '.bin'),
                                    'mime': mime, 'size': len(data), 'review': 'Nicht ausgewertet'})

        visit(msg)
        if msg.defects:
            warnings.append('E-Mail-Struktur enthält Abweichungen; bitte Original prüfen.')
        body = '\n\n'.join(texts).strip()
        body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
        blobs[body_hash] = body.encode('utf-8')
        value = dict(title=str(msg.get('Subject', 'Importierte E-Mail'))[:120],
                     sender=str(msg.get('From', ''))[:500], mail_date=str(msg.get('Date', ''))[:200],
                     source=body if len(body) <= 4000 else '', reply='', revision=uuid.uuid4().hex,
                     original_hash=original, body_hash=body_hash, body_length=len(body), attachments=attachments,
                     warnings=list(dict.fromkeys(warnings)), created_at=stamp(), categories=['general'], status='new')
        if not body:
            value['warnings'].append('Kein lesbarer Klartext. HTML und Anhänge sind nicht ausgewertet. Prüftext bei Bedarf manuell einfügen.')
        elif len(body) > 4000:
            value['warnings'].append('Klartext länger als 4000 Zeichen. Keine automatische Kürzung: bitte einen ausgewiesenen Prüfausschnitt einfügen.')
        return 'eml-' + original, value, blobs
    except (RecursionError, LookupError, UnicodeError) as exc:
        raise ValueError('Diese E-Mail konnte nicht sicher gelesen werden. Kein Import übernommen.') from exc


def update_workflow(value, form):
    categories = list(dict.fromkeys(form.getlist('category')))
    status = form.get('status', 'new')
    document = form.get('document', 'none')
    doc_state = form.get('document_status', 'review')
    if not categories or set(categories) - CATEGORIES.keys() or status not in STATUSES or document not in DOCUMENTS or doc_state not in DOC_STATES:
        raise ValueError('Bitte gültige Kategorien und Status wählen.')
    owner = form.get('owner', '').strip()
    project = form.get('project', '').strip()
    due = form.get('due', '').strip()
    note = form.get('workflow_note', '').strip()
    if max(len(owner), len(project)) > 120 or len(note) > 1000:
        raise ValueError('Verantwortung/Projekt maximal 120, Vermerk maximal 1000 Zeichen.')
    if due:
        try:
            date.fromisoformat(due)
        except ValueError as exc:
            raise ValueError('Bitte ein gültiges Wiedervorlagedatum wählen.') from exc
    if status == 'waiting' and (not due or not note):
        raise ValueError('Beim Warten bitte Wiedervorlage und Kontakt/Anlass im Vermerk festhalten.')
    if status == 'done' and not note:
        raise ValueError('Bitte die tatsächlich erledigte Handlung im Vermerk festhalten.')
    previous = value.get('workflow', {})
    paid = form.get('paid') == 'yes'
    if document == 'none':
        doc_state, paid = 'review', False
    if (doc_state in ('exported', 'handed', 'booked') and doc_state != previous.get('document_status')) or (paid and not previous.get('paid')):
        if form.get('confirm_fact') != 'yes' or not note:
            raise ValueError('Diesen tatsächlichen Vorgang bitte ausdrücklich bestätigen und im Vermerk belegen.')
    document_fields = {key: form.get(key, '').strip() for key in ('supplier', 'document_number', 'document_date', 'amount', 'currency', 'original_reference')}
    if any(len(x) > 200 for x in document_fields.values()):
        raise ValueError('Belegangaben bitte auf jeweils 200 Zeichen begrenzen.')
    if document_fields['document_date']:
        try:
            date.fromisoformat(document_fields['document_date'])
        except ValueError as exc:
            raise ValueError('Ungültiges Belegdatum.') from exc
    if document_fields['amount']:
        try:
            amount = Decimal(document_fields['amount'].replace(',', '.'))
            if not amount.is_finite() or len(document_fields['amount']) > 20:
                raise InvalidOperation
        except InvalidOperation as exc:
            raise ValueError('Betrag bitte als Dezimalzahl ohne Tausendertrennzeichen eingeben.') from exc
    if document_fields['currency'] and not re.fullmatch('[A-Z]{3}', document_fields['currency']):
        raise ValueError('Währung als drei Großbuchstaben, z.B. EUR, eingeben.')
    references = [a['hash'] for a in value.get('attachments', [])] + [value.get('original_hash', '')]
    if document_fields['original_reference'] and document_fields['original_reference'] not in references:
        raise ValueError('Originalbezug gehört nicht zu dieser Nachricht.')
    if document != 'none' and doc_state != 'review' and not document_fields['original_reference']:
        raise ValueError('Für diesen Belegstatus bitte zuerst ein Original zuordnen.')
    identity_changed = document != previous.get('document', 'none') or any(v != previous.get(k, '') for k, v in document_fields.items())
    if identity_changed and (doc_state in ('exported', 'handed', 'booked') or paid) and (form.get('confirm_fact') != 'yes' or not note):
        raise ValueError('Belegangaben geändert: Export, Übergabe, Buchung oder Zahlung erneut ausdrücklich bestätigen oder Status zurücksetzen.')
    workflow = dict(owner=owner, project=project, due=due, note=note, document=document, document_status=doc_state, paid=paid, **document_fields)
    history = list(value.get('workflow_history', []))
    history.append(dict(at=stamp(), categories=categories, status=status, **workflow))
    value.update(categories=categories, status=status, workflow=workflow, workflow_history=history)


def workflow_html(value, fields, escape):
    work = value.get('workflow', {})
    def select(name, title, choices, selected):
        options = ''.join('<option value="' + key + '"' + (' selected' if key == selected else '') + '>' + text + '</option>' for key, text in choices.items())
        return '<label for="' + name + '">' + title + '</label><select id="' + name + '" name="' + name + '">' + options + '</select>'
    def field(name, title, kind='text'):
        return '<label for="' + name + '">' + title + '</label><input id="' + name + '" name="' + name + '" type="' + kind + '" maxlength="120" value="' + escape(work.get(name, '')) + '">'
    categories = ''.join('<label><input type="checkbox" name="category" value="' + key + '"' + (' checked' if key in value.get('categories', ['general']) else '') + '> ' + title + '</label>' for key, title in CATEGORIES.items())
    history = ''.join('<li>' + escape(item['at']) + ' · ' + STATUSES[item['status']] + ' · ' + escape(item['note']) + ' · Beleg: ' + DOC_STATES[item['document_status']] + ' · Zahlung: ' + ('bestätigt' if item['paid'] else 'nicht bestätigt') + '</li>' for item in reversed(value.get('workflow_history', [])))
    references = {'': 'Kein Original ausgewählt'}
    if value.get('original_hash'):
        references[value['original_hash']] = 'Original-EML'
    references.update({a['hash']: escape(a['name']) for a in value.get('attachments', [])})
    return ('<div class="card"><h2>Arbeitsvorgang</h2><p>Mehrere Anliegen können gleichzeitig markiert bleiben. Ein Belegstatus erledigt keine Kundenfrage.</p><form method="post">' + fields + categories +
            select('status', 'Bearbeitung', STATUSES, value.get('status', 'new')) + field('owner', 'Verantwortlich') + field('project', 'Projektbezug (Freitext)') + field('due', 'Wiedervorlage', 'date') +
            select('document', 'Belegart – manuell zugeordnet', DOCUMENTS, work.get('document', 'none')) + select('document_status', 'Belegstatus – manuell bestätigt', DOC_STATES, work.get('document_status', 'review')) +
            '<p>Belegangaben manuell am Original prüfen. Keine automatische Rechnungs- oder PDF-Auswertung.</p>' +
            select('original_reference', 'Zugehöriges Original', references, work.get('original_reference', '')) +
            field('supplier', 'Lieferant') + field('document_number', 'Belegnummer') + field('document_date', 'Belegdatum', 'date') + field('amount', 'Betrag wie im Beleg (Dezimalkomma erlaubt)') + field('currency', 'Währung, z.B. EUR') +
            '<label><input type="checkbox" name="paid" value="yes"' + (' checked' if work.get('paid') else '') + '> Zahlung separat bestätigt</label>' +
            '<label for="workflow_note">Vermerk / Nachweis / offene Frage</label><textarea id="workflow_note" name="workflow_note" maxlength="1000">' + escape(work.get('note', '')) + '</textarea>' +
            '<label><input type="checkbox" name="confirm_fact" value="yes"> Geänderten Export-, Übergabe-, Buchungs- oder Zahlungsvorgang tatsächlich geprüft</label>' +
            '<p>Ein Download setzt keinen Status. Keine Buchung, Zahlung oder Übergabe wird hier ausgeführt.</p><button class="btn" name="action" value="workflow">Arbeitsvorgang speichern</button></form>' +
            ('<details><summary>Änderungsverlauf</summary><ul>' + history + '</ul></details>' if history else '') + '</div>')
