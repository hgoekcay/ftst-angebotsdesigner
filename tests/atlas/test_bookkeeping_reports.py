import copy
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

path = Path(__file__).parents[2] / 'ftst_atlas' / 'bookkeeping_reports.py'
spec = importlib.util.spec_from_file_location('atlas_bookkeeping_reports_test', path)
reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reports)


def record(ident='a', status='OPEN', amount='123.4500', currency='EUR', **extra):
    return {'id': ident, 'source': {'provider': 'billomat'}, 'filename': 'snapshot.json',
            'fields': {'direction': 'outgoing', 'source_status': status, 'source_open_amount': amount,
                       'source_currency': currency, 'currency': 'USD', 'invoice_number': 'RE-' + ident,
                       'source_due_date': '2026-10-15', 'invoice_date': '2026-10-01'},
            'reviewed': False, 'issues': [], **extra}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'db')
        self.app = SimpleNamespace(db=lambda: sqlite3.connect(self.path), bookkeeping=Mock(), bookkeeping_sync=Mock())
        self.app.bookkeeping_sync.enabled_for.side_effect = lambda owner: owner == 'owner'
        self.app.bookkeeping_sync.status.return_value = {'pending': False, 'last_finished': '2026-10-28T12:00:00+00:00'}
        with self.app.db() as db:
            db.executescript('CREATE TABLE atlas_bookkeeping(id TEXT,user_id TEXT); CREATE TABLE atlas_bookkeeping_documents(record_id TEXT,user_id TEXT);')

    def tearDown(self):
        self.tmp.cleanup()

    def setup_records(self, records, originals=()):
        self.app.bookkeeping.list.return_value = records
        with self.app.db() as db:
            db.executemany('INSERT INTO atlas_bookkeeping VALUES (?,?)', [(r['id'], 'owner') for r in records])
            db.executemany('INSERT INTO atlas_bookkeeping_documents VALUES (?,?)', [(ident, 'owner') for ident in originals])

    def test_unfinished_old_invoice_refresh_is_visible_in_op_summary(self):
        self.setup_records([record()])
        self.app.bookkeeping_sync.status.return_value.update(
            pending=True, sources=[{'id': 'billomat_op', 'pending': True, 'remaining': 1}])
        report = reports.build_report(self.app, 'owner')
        self.assertTrue(report['incomplete'])
        self.assertIn('älterer offener Rechnungen', reports.format_report(report, 'op'))

    def test_owner_denial_before_data_read(self):
        with self.assertRaises(reports.ReportError):
            reports.build_report(self.app, 'other')
        self.app.bookkeeping.list.assert_not_called()
        self.app.bookkeeping_sync.status.assert_not_called()

    def test_only_explicit_positive_billomat_op_and_source_currency(self):
        records = [record('a'), record('b', 'OVERDUE', '0.000000000001'), record('c', 'PAID'),
                   record('d', 'CANCELED'), record('e', 'DRAFT'), record('f', amount=''),
                   record('g', amount='0'), record('h', amount='-1'), record('i', amount='NaN'),
                   record('j', currency=''), record('k', status=''), record('l', currency='USD', amount='3.10')]
        incoming = record('m'); incoming['source'] = {'provider': 'upload'}; incoming['fields']['direction'] = 'incoming'
        records.append(incoming)
        self.setup_records(records)
        result = reports.build_report(self.app, 'owner')
        self.assertEqual({r['id'] for r in result['open_items']}, {'a', 'b', 'l'})
        self.assertEqual(result['summary']['open_by_currency'], {'EUR': '123.450000000001', 'USD': '3.10'})
        self.assertEqual(result['summary']['unknown_open'], 4)
        self.assertNotIn('m', {r['id'] for r in result['open_items']})
        text = reports.format_report(result, 'op')
        self.assertIn('Zahlungsstand unbekannt', text)
        self.assertIn('kein Bankabgleich', text)
        self.assertNotIn('bezahlt', text)

    def test_missing_originals_review_reasons_and_owner_scope(self):
        incoming = record('c', source={'provider': 'upload'}, reviewed=True)
        incoming['fields']['direction'] = 'incoming'
        self.setup_records([record('a', issues=['Währung prüfen']), record('b', reviewed=True), incoming], originals=['b'])
        with self.app.db() as db:
            db.execute('INSERT INTO atlas_bookkeeping_documents VALUES (?,?)', ('a', 'other'))
        result = reports.build_report(self.app, 'owner')
        self.assertEqual(result['summary']['missing_originals'], 1)
        self.assertEqual(result['summary']['unreviewed'], 1)
        self.assertEqual(len(result['review_items']), 1)
        self.assertEqual(result['review_items'][0]['id'], 'a')
        self.assertIn('Währung prüfen', result['review_items'][0]['reasons'])
        text = reports.format_report(result, 'belege')
        self.assertIn('ID: a', text)
        self.assertIn('Telegram-Dateiupload wird hier noch nicht verarbeitet', text)
        self.assertIn('manuell geprüft', text)

    def test_incomplete_and_bounded_messages(self):
        records = [record(str(i), issues=['Langer Grund ' * 30]) for i in range(40)]
        self.setup_records(records)
        self.app.bookkeeping_sync.status.return_value['pending'] = True
        result = reports.build_report(self.app, 'owner')
        self.assertTrue(result['incomplete'])
        for kind in ('summary', 'op', 'belege'):
            text = reports.format_report(result, kind)
            self.assertLessEqual(len(text), 3900)
            self.assertIn('Teilbestand', text)
            self.assertIn('kein Bankabgleich', text)
        self.assertIn('Weitere', reports.format_report(result, 'belege'))

    def test_no_completed_import_is_not_a_complete_empty_ledger(self):
        self.setup_records([])
        self.app.bookkeeping_sync.status.return_value = {'pending': False}
        result = reports.build_report(self.app, 'owner')
        self.assertTrue(result['incomplete'])
        self.assertIn('noch kein abgeschlossener Import', reports.format_report(result, 'op'))

    def test_report_uses_only_local_services_and_keeps_inputs(self):
        original = record()
        expected = copy.deepcopy(original)
        self.setup_records([original])
        self.app.respond = Mock(side_effect=AssertionError('No model'))
        self.app.billomat = Mock(side_effect=AssertionError('No network'))
        result = reports.build_report(self.app, 'owner')
        self.assertEqual(original, expected)
        self.app.respond.assert_not_called()
        self.app.bookkeeping.list.assert_called_once_with('owner')
        self.assertTrue(result['read_only'])


if __name__ == '__main__':
    unittest.main()
