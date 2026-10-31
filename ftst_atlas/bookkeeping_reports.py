"""Deterministic owner-scoped preparation reports from locally stored evidence.

No provider or model requests. Billomat balances describe the last imported
source state, not bank reconciliation or a complete accounts-receivable ledger.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re


class ReportError(ValueError):
    pass


def _amount(value):
    if not isinstance(value, str) or not re.fullmatch(r'-?\d{1,15}(?:\.\d{1,12})?', value):
        return None
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def _text(value, length=150):
    return ' '.join(str(value or '').split())[:length]


def build_report(app, user_id):
    sync = getattr(app, 'bookkeeping_sync', None)
    if sync is None or not sync.enabled_for(user_id):
        raise ReportError('Buchhaltung ist für dieses Profil nicht freigegeben.')
    records = app.bookkeeping.list(user_id)
    with app.db() as db:
        originals = {row[0] for row in db.execute('SELECT record_id FROM atlas_bookkeeping_documents WHERE user_id=?', (user_id,))}
        total = db.execute('SELECT COUNT(*) FROM atlas_bookkeeping WHERE user_id=?', (user_id,)).fetchone()[0]
    open_items, review_items, balances = [], [], {}
    unknown_open = 0
    unreviewed = 0
    missing = 0
    for record in records:
        fields, source = record['fields'], record['source']
        billomat = source.get('provider', source.get('type')) == 'billomat'
        source_status = fields.get('source_status', '')
        title = _text(fields.get('invoice_number') or record.get('filename'))
        reasons = [_text(reason, 200) for reason in record.get('issues', [])]
        if not record.get('reviewed'):
            unreviewed += 1
            reasons.insert(0, 'Noch nicht geprüft')
        no_original = billomat and record['id'] not in originals
        if no_original:
            missing += 1
            reasons.insert(0, 'Billomat-Originalbeleg noch nicht hinterlegt')
        if reasons:
            review_items.append({'id': record['id'], 'invoice_number': title,
                                 'direction': fields.get('direction', ''), 'missing_original': no_original,
                                 'reviewed': bool(record.get('reviewed')), 'reasons': list(dict.fromkeys(reasons))})
        if billomat and fields.get('direction') == 'outgoing' and source_status in ('OPEN', 'OVERDUE'):
            amount = _amount(fields.get('source_open_amount', ''))
            currency = fields.get('source_currency', '')
            if amount is None or not isinstance(currency, str) or not re.fullmatch('[A-Z]{3}', currency):
                unknown_open += 1
            elif amount > 0:
                open_items.append({'id': record['id'], 'invoice_number': title, 'invoice_date': fields.get('invoice_date', ''),
                                   'due_date': fields.get('source_due_date', ''), 'source_status': source_status,
                                   'open_amount': format(amount, 'f'), 'currency': currency})
                with localcontext() as context:
                    context.prec = 50
                    balances[currency] = balances.get(currency, Decimal(0)) + amount
        elif billomat and fields.get('direction') == 'outgoing' and not source_status:
            unknown_open += 1
    open_items.sort(key=lambda item: (item['due_date'] or '9999-12-31', item['invoice_number'], item['id']))
    status = sync.status(user_id)
    return {'generated_at': datetime.now(timezone.utc).isoformat(), 'read_only': True,
            'summary': {'records': total, 'listed_records': len(records), 'open_items': len(open_items),
                        'unknown_open': unknown_open, 'unreviewed': unreviewed, 'missing_originals': missing,
                        'review_items': len(review_items), 'open_by_currency': {key: format(value, 'f') for key, value in sorted(balances.items())}},
            'open_items': open_items, 'review_items': review_items, 'sync': status,
            'incomplete': total != len(records) or not status.get('last_finished') or bool(status.get('pending') or status.get('errors')),
            'limitations': ['Nur lokal importierte Daten; Zahlungsstände können inzwischen geändert sein.',
                            'Eingangs-OP und weitere fehlende Belege sind ohne vollständigen Bankabgleich nicht verlässlich bestimmbar.',
                            'Belegvorbereitung zur Prüfung, keine fertige Buchhaltung.']}


def format_report(report, kind='summary'):
    if kind not in ('summary', 'op', 'belege'):
        raise ReportError('Unbekannter Bericht.')
    summary = report['summary']
    stamp = report['sync'].get('last_finished') or report['sync'].get('last_run') or 'noch kein abgeschlossener Import'
    lines = ['ATLAS · ' + {'summary': 'Buchhaltung', 'op': 'Offene Ausgangsrechnungen', 'belege': 'Belege zur Klärung'}[kind],
             'Importstand: ' + _text(stamp, 70)]
    if report['incomplete']:
        lines.append('Import/Auswahl unvollständig – Angaben sind ein Teilbestand.')
    if any(source.get('id') == 'billomat_op' and source.get('pending') for source in report['sync'].get('sources', [])):
        lines.append('Zahlungsstände älterer offener Rechnungen sind noch nicht vollständig aktualisiert.')
    if kind in ('summary', 'op'):
        lines.append(str(summary['open_items']) + ' offene Ausgangsrechnungen im importierten Billomat-Bestand.')
        lines.extend(amount + ' ' + currency + ' offen' for currency, amount in list(summary['open_by_currency'].items())[:8])
        if len(summary['open_by_currency']) > 8:
            lines.append('Weitere Währungen in ATLAS → Buchhaltung.')
        if summary['unknown_open']:
            lines.append(str(summary['unknown_open']) + ' weitere Rechnungen: offener Betrag/Zahlungsstand unbekannt.')
    if kind == 'op':
        for item in report['open_items'][:10]:
            lines.append('• ' + _text(item['invoice_number'], 70) + ': ' + item['open_amount'] + ' ' + item['currency']
                         + ' · fällig ' + (item['due_date'] or 'unbekannt') + '\n  ID: ' + item['id'])
        if len(report['open_items']) > 10:
            lines.append('Weitere ' + str(len(report['open_items']) - 10) + ' Einträge in ATLAS → Buchhaltung.')
    if kind in ('summary', 'belege'):
        lines.append(str(summary['missing_originals']) + ' Originalbelege noch nicht hinterlegt; ' + str(summary['unreviewed']) + ' Belege ungeprüft.')
    if kind == 'belege':
        shown = 0
        for item in report['review_items'][:10]:
            line = '• ' + _text(item['invoice_number'], 65) + '\n  ID: ' + item['id'] + '\n  Grund: ' + '; '.join(item['reasons'][:3])
            if sum(len(value) + 1 for value in lines) + len(line) > 2850:
                break
            lines.append(line)
            shown += 1
        if len(report['review_items']) > shown:
            lines.append('Weitere ' + str(len(report['review_items']) - shown) + ' Einträge in ATLAS → Buchhaltung.')
        lines.append('Nachreichen: ATLAS → Buchhaltung → Beleg hochladen. Die Zuordnung zu dieser ID muss anschließend manuell geprüft werden. Telegram-Dateiupload wird hier noch nicht verarbeitet.')
    if kind == 'summary':
        lines.append('/op zeigt die Liste; /belege zeigt IDs und Klärungsgründe.')
    lines.append('Nur importierter Stand; kein Bankabgleich. Eingangs-OP und weitere fehlende Belege bleiben ungeklärt.')
    return '\n'.join(lines)[:3900]
