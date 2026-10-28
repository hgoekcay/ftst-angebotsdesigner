"""Conservative adapter to Billpal AI Bookkeeping documents/1.

Contract reviewed against leebale/billpal-skills at
8ccff9c7cbd1b568e3bd469a4d457b50ab381781: ai-bookkeeping/input-files.md
and ledger.py (DOC_KEYS, norm_doc, stage_documents). No upstream code copied.

ATLAS captures aggregate invoice fields, not verified tax regimes, line items,
credit-note links or booking decisions. Every exported document is held for
review, even when its ATLAS extraction was reviewed. Missing required values
stay in the ordinary manifest and are explicitly listed in this file's notes.
This adapter neither produces bookings nor marks a payment as confirmed.
"""
from datetime import date
from decimal import Decimal
import re


_MONEY = re.compile(r'-?\d{1,12}(?:\.\d{1,2})?')
_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def _text(value, limit=300):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _amount(value):
    # The source contract uses exact strings. Never silently round or coerce floats.
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        return None
    return Decimal(value)


def documents_v1(records):
    """Return an upstream-compatible documents/1 envelope with honest omissions.

    `records` is the owner-filtered ATLAS export manifest, not raw database rows.
    `notes` follows upstream from-billpal's envelope extension. Unsupported records
    remain in the original manifest; this output does not claim completeness.
    EUR is the only supported currency here: the source fields cannot supply the
    FX rate required by the intended EUR ledger for other currencies.
    """
    if not isinstance(records, list):
        raise ValueError('Belegexport benötigt eine Liste.')
    documents, notes, seen = [], [], set()
    for position, record in enumerate(records, 1):
        label = f'Beleg {position}'
        if not isinstance(record, dict):
            notes.append(f'{label}: nicht übernommen; ungültiger Datensatz. Originalmanifest prüfen.')
            continue
        ident = record.get('id')
        if not isinstance(ident, str) or not _ID.fullmatch(ident):
            notes.append(f'{label}: nicht übernommen; gültige ATLAS-ID fehlt.')
            continue
        label = 'atlas:' + ident
        if ident in seen:
            notes.append(f'{label}: doppelte ID nicht erneut übernommen; Originalmanifest prüfen.')
            continue
        seen.add(ident)
        fields = record.get('fields')
        if not isinstance(fields, dict):
            notes.append(f'{label}: nicht übernommen; Belegfelder fehlen.')
            continue
        problems = []
        source_status = fields.get('source_status', '')
        issues = record.get('issues') if isinstance(record.get('issues'), list) else []
        canceled = (record.get('status') == 'canceled'
                    or (isinstance(source_status, str) and source_status.upper() in ('CANCELED', 'DRAFT'))
                    or any(isinstance(issue, str) and re.search(r'\bstorn', issue, re.I)
                           for issue in issues))
        if canceled:
            notes.append(f'{label}: nicht übernommen; stornierter Beleg oder Entwurf. Original im Manifest prüfen.')
            continue
        direction_value = fields.get('direction')
        direction = {'incoming': 'in', 'outgoing': 'out'}.get(direction_value) if isinstance(direction_value, str) else None
        if direction is None:
            problems.append('Belegrichtung fehlt')
        elif record.get('direction') not in (None, fields['direction']):
            problems.append('Belegrichtung widersprüchlich')
        for key in ('supplier', 'invoice_number'):
            if not _text(fields.get(key)):
                problems.append(f'{key} fehlt oder ist ungültig')
        stamp = fields.get('invoice_date')
        try:
            if not isinstance(stamp, str) or date.fromisoformat(stamp).isoformat() != stamp:
                raise ValueError()
        except ValueError:
            problems.append('gültiges Rechnungsdatum fehlt')
        if fields.get('currency') != 'EUR':
            problems.append('EUR-Währung fehlt oder Fremdwährung benötigt bestätigten Wechselkurs')
        amounts = {key: _amount(fields.get(key)) for key in ('net', 'tax', 'gross')}
        if any(value is None for value in amounts.values()):
            problems.append('exakte Netto-, Steuer- oder Bruttobeträge fehlen')
        else:
            if amounts['net'] + amounts['tax'] != amounts['gross']:
                problems.append('Netto plus Steuer weicht von Brutto ab')
            if any(value < 0 for value in amounts.values()):
                problems.append('negative Beträge benötigen bestätigte Belegart und Gutschriftzuordnung')
        if problems:
            notes.append(f'{label}: nicht übernommen; ' + '; '.join(problems) + '. Original im Manifest prüfen.')
            continue
        # Generic imports may also be receipts or reminders; do not label them as
        # invoices from their filename, amount, payment status, or extraction alone.
        source = record.get('source')
        is_billomat_invoice = (isinstance(source, dict) and source.get('provider') == 'billomat'
                              and bool(source.get('invoice_id')) and direction == 'out')
        note = ('ATLAS-Belegvorbereitung, keine Buchung. Netto ' + format(amounts['net'], '.2f')
                + ' EUR; ausgewiesener Gesamtsteuerbetrag ' + format(amounts['tax'], '.2f')
                + ' EUR. Steuerregime, Steuersätze, Positionen, Kontierung und Belegart noch prüfen. '
                'Ein Zahlungsstatus in ATLAS ist kein Zahlungsnachweis. Original und Prüfverlauf im Manifest.')
        documents.append({
            'id': label, 'kind': 'invoice' if is_billomat_invoice else 'other',
            'direction': direction, 'number': fields['invoice_number'].strip(),
            'date': stamp, 'currency': 'EUR', 'party': {'name': fields['supplier'].strip()},
            'total': format(amounts['gross'], '.2f'),
            'lines': [{'amount': format(amounts['gross'], '.2f'), 'amount_is': 'gross',
                       'description': 'Gesamtbetrag; Positions- und Steueraufteilung noch zu prüfen'}],
            'review_open': True, 'source': 'atlas', 'note': note,
        })
        notes.append(f'{label}: als prüfpflichtiger Beleg übernommen; keine Steuer- oder Buchungsfreigabe.')
    notes.insert(0, 'Alle enthaltenen Belege bleiben review_open=true. Fehlende Belege, '
                 'Fremdwährungen und unvollständige oder widersprüchliche Angaben stehen im '
                 'ATLAS-Originalmanifest. Dies ist kein vollständiges Buchungsjournal oder DATEV-Export.')
    return {'schema': 'documents/1', 'documents': documents, 'notes': notes}
