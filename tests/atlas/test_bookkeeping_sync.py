import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).parents[2] / 'ftst_atlas'
sys.path.insert(0, str(ROOT))
try:
    spec = importlib.util.spec_from_file_location('atlas_bookkeeping_sync_tests', ROOT / 'bookkeeping_sync.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
finally:
    sys.path.pop(0)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = lambda: sqlite3.connect(str(Path(self.tmp.name) / 'db.sqlite'), timeout=5)
        self.options = {'bookkeeping_enabled': True, 'bookkeeping_ha_user_id': 'owner', 'mail_account_ids': ['primary']}
        self.book, self.mail, self.bill = Mock(), Mock(), Mock()
        self.mail.enabled_for.return_value = True
        self.mail.accounts.return_value = [{'id': 'primary', 'email': 'a@example.test', 'folder': 'INBOX'}, {'id': 'unapproved', 'email': 'b@example.test', 'folder': 'INBOX'}]
        self.bill.enabled_for.return_value = False
        self.bill.host = 'test.billomat.net'
        self.book.ingest_document.return_value = {'id': 'doc'}
        self.book.ingest_billomat.return_value = {'id': 'invoice'}
        self.mail.invoice_batch.return_value = self.batch()
        self.sync = self.make()

    def tearDown(self):
        self.sync.stop()
        self.tmp.cleanup()

    def make(self):
        return module.BookkeepingSync(self.options, self.db, self.book, self.mail, self.bill)

    def batch(self, uid=4, pending=False, warnings=None):
        return {'source': {'account_id': 'primary', 'mailbox': 'a@example.test', 'folder': 'INBOX'}, 'uidvalidity': 17,
                'after_uid': uid, 'pending': pending, 'messages': [{'uid': uid, 'warnings': warnings or [], 'attachments': [
                    {'name': 'r.pdf', 'content_type': 'application/pdf', 'data': b'%PDF-data', 'source': {'part_index': 2}}]}]}

    def row(self, ident='1'):
        return {'id': ident, 'status': 'OPEN', 'invoice_number': 'R' + ident, 'date': '2026-10-01', 'currency_code': 'EUR',
                'total_net': '10.00', 'total_gross': '11.90', 'paid_amount': '0'}

    def page(self, rows, pending=False, next_page=None, total=None):
        return {'invoices': rows, 'pending': pending, 'next_page': next_page, 'total': len(rows) if total is None else total}

    def test_owner_default_disabled_and_no_silent_account_grant(self):
        self.assertFalse(self.make().enabled_for('other'))
        with self.assertRaises(module.SyncError):
            self.sync.sync('other')
        self.assertEqual(self.sync.status('other'), {'enabled': False, 'auto_sync': False, 'running': False})
        self.sync.sync('owner')
        self.assertEqual(self.mail.invoice_batch.call_args.args[1], 'primary')
        self.options['bookkeeping_enabled'] = False
        self.assertFalse(self.make().enabled_for('owner'))
        self.sync.start()
        self.assertIsNone(self.sync._thread)

    def test_checkpoint_persists_after_ingest_and_resume_exact_window(self):
        self.sync.sync('owner')
        state = self.sync._get('mail:primary')
        self.assertEqual(state['after_uid'], 4)
        self.assertEqual(state['uidvalidity'], 17)
        self.sync = self.make()
        self.sync.sync('owner')
        self.assertEqual(self.mail.invoice_batch.call_args.kwargs, {'after_uid': 4, 'uidvalidity': 17, 'since': state['since']})
        source = self.book.ingest_document.call_args.args[-1]
        self.assertEqual(source['message_uid'], '17:4')
        self.assertNotIn('a@example.test', str(source))

    def test_partial_document_failure_never_advances_batch_and_redacts_error(self):
        batch = self.batch()
        batch['messages'][0]['attachments'] *= 2
        self.mail.invoice_batch.return_value = batch
        self.book.ingest_document.side_effect = [{'id': 'first'}, RuntimeError('secret-token-body')]
        result = self.sync.sync('owner')
        self.assertEqual(self.sync._get('mail:primary')['after_uid'], 0)
        self.assertTrue(result['pending'])
        self.assertNotIn('secret-token-body', str(result))
        self.book.ingest_document.side_effect = None
        self.sync.sync('owner')
        self.assertEqual(self.sync._get('mail:primary')['after_uid'], 4)

    def test_source_binding_change_and_uidvalidity_reset_never_cross_skip(self):
        self.sync.sync('owner')
        self.mail.accounts.return_value[0]['folder'] = 'Archive'
        batch = self.batch()
        batch['source']['folder'] = 'Archive'
        self.mail.invoice_batch.return_value = batch
        self.sync.sync('owner')
        self.assertEqual(self.mail.invoice_batch.call_args.kwargs['after_uid'], 0)
        self.assertTrue(self.sync.status('owner')['pending'])
        self.mail.invoice_batch.side_effect = module.UIDValidityChanged('secret')
        self.sync.sync('owner')
        self.assertEqual(self.sync._get('mail:primary')['after_uid'], 0)
        self.assertIsNone(self.sync._get('mail:primary')['uidvalidity'])

    def test_returned_source_mismatch_blocks_documents_and_cursor(self):
        batch = self.batch()
        batch['source']['mailbox'] = 'other@example.test'
        self.mail.invoice_batch.return_value = batch
        self.sync.sync('owner')
        self.book.ingest_document.assert_not_called()
        self.assertEqual(self.sync._get('mail:primary')['after_uid'], 0)

    def test_three_batch_limit_and_warning_markers_persist(self):
        self.mail.invoice_batch.side_effect = [self.batch(i, True, ['ignored-secret']) for i in range(1, 4)]
        result = self.sync.sync('owner')
        self.assertEqual(self.mail.invoice_batch.call_count, 3)
        self.assertEqual(result['counts']['mail_messages'], 3)
        self.assertEqual(result['sources'][0]['warnings'], 3)
        self.assertNotIn('ignored-secret', str(result))
        self.assertEqual(self.make().status('owner')['sources'][0]['warnings'], 3)

    def test_billomat_pages_persist_window_pdf_budget_and_rescan(self):
        self.mail.enabled_for.return_value = False
        self.bill.enabled_for.return_value = True
        self.bill.list_invoices.side_effect = [self.page([self.row(str(i)) for i in range(n, n + 25)], True, p + 1, 100)
                                                for p, n in [(1, 1), (2, 26), (3, 51)]]
        result = self.sync.sync('owner')
        state = self.sync._get('billomat')
        self.assertEqual(state['page'], 4)
        self.assertEqual(result['counts']['billomat_invoices'], 75)
        self.assertEqual(self.bill.get_pdf.call_count, 5)
        self.assertEqual(result['pending_pdfs'], 70)
        self.bill.list_invoices.side_effect = None
        self.bill.list_invoices.return_value = self.page([self.row(str(i)) for i in range(76, 101)], total=100)
        self.sync = self.make()
        self.sync.sync('owner')
        self.assertEqual(self.bill.list_invoices.call_args.args, ('owner', state['date_from'], state['date_to']))
        self.assertEqual(self.bill.list_invoices.call_args.kwargs, {'page': 4})
        self.bill.list_invoices.return_value = self.page([self.row()])
        self.sync.sync('owner')
        self.assertEqual(self.bill.list_invoices.call_args.kwargs, {'page': 1})

    def test_live_page_total_change_restarts_without_skipping(self):
        self.mail.enabled_for.return_value = False
        self.bill.enabled_for.return_value = True
        self.bill.list_invoices.side_effect = [self.page([self.row()], True, 2, 2), self.page([self.row('2')], total=3)]
        result = self.sync.sync('owner')
        self.assertTrue(result['pending'])
        self.assertEqual(self.sync._get('billomat')['page'], 1)
        self.book.ingest_billomat.assert_called_once()

    def test_billomat_host_change_blocks_old_id_pdf_association(self):
        self.mail.enabled_for.return_value = False
        self.bill.enabled_for.return_value = True
        self.bill.list_invoices.return_value = self.page([self.row()])
        self.bill.get_pdf.side_effect = RuntimeError('secret')
        self.sync.sync('owner')
        self.bill.host = 'new.billomat.net'
        self.bill.get_pdf.reset_mock()
        self.bill.list_invoices.reset_mock()
        result = self.sync.sync('owner')
        self.bill.list_invoices.assert_not_called()
        self.bill.get_pdf.assert_not_called()
        self.assertTrue(result['sources'][0]['binding_changed'])

    def test_lock_prevents_overlap_and_stop_interrupts_remaining_batches(self):
        entered, release = threading.Event(), threading.Event()
        def batch(*args, **kwargs):
            entered.set()
            release.wait(3)
            return self.batch(pending=True)
        self.mail.invoice_batch.side_effect = batch
        thread = threading.Thread(target=self.sync.sync, args=('owner',))
        thread.start()
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(module.SyncError):
                self.sync.sync('owner')
            self.assertTrue(self.sync.status('owner')['running'])
            self.sync.stop(0)
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(self.mail.invoice_batch.call_count, 1)

    def test_auto_requires_explicit_flag_and_can_be_stopped(self):
        self.options['bookkeeping_auto_sync'] = True
        self.sync = self.make()
        done = threading.Event()
        original = self.sync.sync
        def call(user):
            result = original(user)
            done.set()
            return result
        self.sync.sync = call
        self.sync.start()
        self.assertTrue(done.wait(3))
        self.sync.stop()
        self.assertFalse(self.sync._thread.is_alive())
        self.assertEqual(self.mail.invoice_batch.call_count, 1)

    def real_bookkeeping(self):
        spec = importlib.util.spec_from_file_location('atlas_bookkeeping_sync_integration', ROOT / 'bookkeeping.py')
        bookkeeping = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT))
        try:
            spec.loader.exec_module(bookkeeping)
        finally:
            sys.path.pop(0)
        self.book = bookkeeping.Bookkeeping(self.db, self.tmp.name)

    def test_real_bookkeeping_ingests_mail_and_refreshes_canceled_invoice(self):
        self.real_bookkeeping()
        self.bill.get_invoice.side_effect = lambda user, ident: self.bill.list_invoices.return_value['invoices'][0]
        batch = self.batch()
        attachment = batch['messages'][0]['attachments'][0]
        attachment.update(name='receipt.png', content_type='image/png', data=b'\x89PNG\r\n\x1a\nsynthetic')
        self.mail.invoice_batch.return_value = batch
        self.bill.enabled_for.return_value = True
        self.bill.list_invoices.return_value = self.page([self.row()])
        self.bill.get_pdf.return_value = b'%PDF-1.7\nsynthetic\n%%EOF'
        self.sync = self.make()
        first = self.sync.sync('owner')
        self.assertFalse(first['errors'])
        self.assertEqual(first['counts']['documents'], 1)
        self.assertEqual(first['counts']['pdfs'], 1)
        records = self.book.list('owner')
        self.assertEqual(len(records), 2)
        invoice = next(r for r in records if r['source']['type'] == 'billomat')
        self.book.review('owner', invoice['id'], {'supplier': 'FTST', 'tax': '1.90', 'reviewed': True})
        canceled = self.row()
        canceled['status'] = 'CANCELED'
        self.bill.list_invoices.return_value = self.page([canceled])
        result = self.sync.sync('owner')
        current = self.book.get('owner', invoice['id'])
        self.assertEqual(len(self.book.list('owner')), 2)
        self.assertFalse(current['reviewed'])
        self.assertEqual(current['fields']['payment_status'], 'unknown')
        self.assertTrue(any('storn' in issue.lower() or 'cancel' in issue.lower() for issue in current['issues']))
        self.assertEqual(len(current['snapshots']), 2)
        self.assertEqual(self.book.get_document('owner', invoice['id'])[0], self.bill.get_pdf.return_value)
        self.assertTrue(result['pending'])

    def test_old_invoice_paid_outside_discovery_window_leaves_op_report(self):
        self.real_bookkeeping()
        self.mail.enabled_for.return_value = False
        self.bill.enabled_for.return_value = True
        old = self.row()
        old.update(date='2020-01-01', open_amount='11.90')
        saved = self.book.ingest_billomat('owner', self.sync._normalize(old))
        self.bill.list_invoices.return_value = self.page([])
        paid = dict(old, status='PAID', paid_amount='11.90', open_amount='0')
        self.bill.get_invoice.return_value = paid
        self.sync = self.make()
        result = self.sync.sync('owner')
        self.bill.get_invoice.assert_called_once_with('owner', '1')
        self.assertGreater(self.bill.list_invoices.call_args.args[1], old['date'])
        self.assertFalse(result['pending'])
        self.assertEqual(self.book.get('owner', saved['id'])['fields']['source_status'], 'PAID')
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location('sync_reports', ROOT / 'bookkeeping_reports.py')
        reports = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reports)
        report = reports.build_report(SimpleNamespace(db=self.db, bookkeeping=self.book, bookkeeping_sync=self.sync), 'owner')
        self.assertEqual(report['summary']['open_items'], 0)
        self.assertEqual(report['summary']['open_by_currency'], {})

    def test_open_refresh_is_bounded_resumes_and_exposes_failed_coverage(self):
        self.real_bookkeeping()
        self.mail.enabled_for.return_value = False
        self.bill.enabled_for.return_value = True
        self.bill.list_invoices.return_value = self.page([])
        for ident in range(1, 28):
            self.book.ingest_billomat('owner', self.sync._normalize(dict(self.row(str(ident)), date='2020-01-01')))
        # Another owner's records must never be sent to Billomat.
        self.book.ingest_billomat('other', self.sync._normalize(self.row('99')))
        def fetch(user, ident):
            if ident == '1':
                raise RuntimeError('private provider details')
            return dict(self.row(ident), date='2020-01-01')
        self.bill.get_invoice.side_effect = fetch
        self.sync = self.make()
        first = self.sync.sync('owner')
        self.assertEqual(self.bill.get_invoice.call_count, 25)
        self.assertTrue(first['pending'])
        self.assertNotIn('private provider details', str(first))
        started = self.sync._get('billomat_op')['started_at']
        self.sync = self.make()
        second = self.sync.sync('owner')
        self.assertTrue(second['pending'])
        self.assertEqual(self.sync._get('billomat_op')['started_at'], started)
        self.assertEqual(self.sync._get('billomat_op')['remaining'], 1)
        self.assertNotIn('99', [call.args[1] for call in self.bill.get_invoice.call_args_list])
        self.bill.get_invoice.side_effect = lambda user, ident: self.row(ident)
        final = self.sync.sync('owner')
        self.assertFalse(final['pending'])
        self.assertEqual(self.sync._get('billomat_op')['remaining'], 0)
        self.assertEqual(self.bill.get_invoice.call_args.args, ('owner', '1'))

    def test_missing_configured_account_is_visible(self):
        self.mail.accounts.return_value = []
        result = self.sync.sync('owner')
        self.assertTrue(result['pending'])
        self.assertIn('nicht verfügbar', result['sources'][0]['error'])
        self.mail.invoice_batch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
