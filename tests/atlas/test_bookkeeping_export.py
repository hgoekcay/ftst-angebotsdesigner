"""The bridge must keep uncertain extracts out of bookable records."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('atlas_bookkeeping_export', Path(__file__).parents[2] / 'ftst_atlas/bookkeeping_export.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record():
    return {'id': 'record_123', 'direction': 'incoming', 'reviewed': True, 'status': 'reviewed',
            'source': {'provider': 'upload'}, 'fields': {
                'direction': 'incoming', 'supplier': 'Beispiel GmbH', 'invoice_number': 'R-2026-1',
                'invoice_date': '2026-10-28', 'currency': 'EUR', 'net': '100.00',
                'tax': '19.00', 'gross': '119.00', 'payment_status': 'paid'}}


class DocumentsExportTests(unittest.TestCase):
    def test_reviewed_paid_extract_still_held_without_invented_tax_or_accounts(self):
        source = record()
        before = copy.deepcopy(source)
        result = module.documents_v1([source])
        doc = result['documents'][0]
        self.assertEqual(result['schema'], 'documents/1')
        self.assertTrue(doc['review_open'])
        self.assertEqual(doc['kind'], 'other')
        self.assertEqual(doc['direction'], 'in')
        self.assertEqual(doc['total'], '119.00')
        self.assertNotIn('taxes', doc)
        self.assertNotIn('tax', doc['lines'][0])
        self.assertNotIn('account', doc['lines'][0])
        self.assertNotIn('payment_status', doc)
        self.assertEqual(source, before)

    def test_billomat_outgoing_invoice_keeps_direction_and_does_not_mark_paid(self):
        source = record()
        source['source'] = {'provider': 'billomat', 'invoice_id': '123'}
        source['direction'] = source['fields']['direction'] = 'outgoing'
        result = module.documents_v1([source])['documents'][0]
        self.assertEqual((result['kind'], result['direction']), ('invoice', 'out'))
        self.assertEqual(result['id'], 'atlas:record_123')
        self.assertTrue(result['review_open'])

    def test_missing_core_values_remain_explicit_omissions_not_defaults(self):
        for key in ('supplier', 'invoice_number', 'invoice_date', 'currency', 'net', 'tax', 'gross', 'direction'):
            with self.subTest(key=key):
                source = record()
                source['fields'][key] = ''
                result = module.documents_v1([source])
                self.assertEqual(result['documents'], [])
                self.assertIn('nicht übernommen', result['notes'][1])

    def test_invalid_amounts_and_dates_are_not_coerced(self):
        for key, value in [('gross', 119.0), ('gross', 'NaN'), ('gross', '119,00'),
                           ('gross', '119.001'), ('gross', '120.00'), ('tax', '-19.00'),
                           ('invoice_date', '2026-02-30'), ('invoice_date', '20261028'),
                           ('currency', 'USD')]:
            with self.subTest(key=key, value=value):
                source = record()
                source['fields'][key] = value
                self.assertEqual(module.documents_v1([source])['documents'], [])

    def test_negative_totals_do_not_infer_credit_notes(self):
        source = record()
        source['fields'].update(net='-100.00', tax='-19.00', gross='-119.00')
        result = module.documents_v1([source])
        self.assertEqual(result['documents'], [])
        self.assertIn('Gutschriftzuordnung', result['notes'][1])

    def test_zero_tax_does_not_infer_exemption(self):
        source = record()
        source['fields'].update(net='119.00', tax='0.00')
        doc = module.documents_v1([source])['documents'][0]
        self.assertTrue(doc['review_open'])
        self.assertNotIn('taxes', doc)
        self.assertNotIn('tax', doc['lines'][0])

    def test_duplicate_and_malformed_rows_do_not_silently_disappear(self):
        result = module.documents_v1([record(), record(), None, {'id': '../unsafe'}])
        self.assertEqual(len(result['documents']), 1)
        self.assertEqual(len(result['notes']), 5)
        self.assertIn('doppelte ID', result['notes'][2])
        with self.assertRaises(ValueError):
            module.documents_v1({'records': []})

    def test_canceled_and_draft_sources_never_enter_ledger_bridge(self):
        for change in ('CANCELED', 'DRAFT', 'status', 'issue'):
            with self.subTest(change=change):
                source = record()
                if change == 'status':
                    source['status'] = 'canceled'
                elif change == 'issue':
                    source['issues'] = ['Stornierte Rechnung prüfen']
                else:
                    source['fields']['source_status'] = change
                result = module.documents_v1([source])
                self.assertEqual(result['documents'], [])
                self.assertIn('stornierter Beleg oder Entwurf', result['notes'][1])

    def test_conflicting_direction_is_not_exported(self):
        source = record()
        source['direction'] = 'outgoing'
        self.assertEqual(module.documents_v1([source])['documents'], [])


if __name__ == '__main__':
    unittest.main()
