import importlib.util
import json
from pathlib import Path
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('atlas_billomat_test', Path(__file__).parents[2] / 'ftst_atlas/atlas_billomat_client.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
KEY = 'private-test-key'
OPTIONS = {'billomat_enabled': True, 'billomat_ha_user_id': 'owner',
           'billomat_subdomain': 'example-company', 'billomat_api_key': KEY}


def row(ident='1', **values):
    return dict({'id': ident, 'client_id': '7', 'invoice_number': 'RE-' + ident,
                 'status': 'OPEN', 'date': '2026-10-01', 'due_date': '2026-10-15',
                 'currency_code': 'EUR', 'total_net': '100.00', 'total_gross': '119.00',
                 'paid_amount': '0.00', 'open_amount': '119.00',
                 'taxes': {'tax': {'name': 'MwSt', 'rate': '19.00', 'amount': '19.00'}}}, **values)


def page(rows, total=None, current=1):
    return {'invoices': {'@page': str(current), '@per_page': '25',
                         '@total': str(len(rows) if total is None else total), 'invoice': rows}}


class BillomatTests(unittest.TestCase):
    def setUp(self):
        self.client = m.BillomatClient(OPTIONS)

    def test_disabled_unconfigured_foreign_owner_never_contact_provider(self):
        with patch.object(m, '_read') as read:
            for options, owner in [(dict(OPTIONS, billomat_enabled=False), 'owner'),
                                   (dict(OPTIONS, billomat_api_key=''), 'owner'), (OPTIONS, 'other'),
                                   (dict(OPTIONS, billomat_subdomain='example.com@evil'), 'owner')]:
                client = m.BillomatClient(options)
                self.assertFalse(client.enabled_for(owner))
                self.assertNotIn(KEY, json.dumps(client.status(owner)))
                for action in [lambda: client.list_invoices(owner, '2026-10-01', '2026-10-31'),
                               lambda: client.get_invoice(owner, '1'), lambda: client.get_pdf(owner, '1')]:
                    with self.assertRaises(m.BillomatError): action()
            read.assert_not_called()

    def test_page_filter_total_next_cursor_and_exact_decimals(self):
        rows = [row(str(i)) for i in range(1, 26)]
        rows[0]['total_net'] = Decimal('100.000000000001')
        with patch.object(m, '_read', return_value=page(rows, total=26)) as read:
            result = self.client.list_invoices('owner', '2026-10-01', '2026-10-31', status='OPEN')
            self.assertEqual(result['next_page'], 2)
            self.assertTrue(result['pending'])
            self.assertEqual(result['total'], 26)
            self.assertEqual(result['invoices'][0]['total_net'], '100.000000000001')
            self.assertFalse(result['snapshot'])
            self.assertEqual(read.call_args.args[0], 'example-company.billomat.net')
            self.assertEqual(read.call_args.args[2], '/api/invoices')
            self.assertEqual(read.call_args.args[3], {'from': '2026-10-01', 'to': '2026-10-31',
                'per_page': 25, 'page': 1, 'order_by': 'date ASC,id ASC', 'status': 'OPEN'})
        with patch.object(m, '_read', return_value=page([row('26')], total=26, current=2)):
            result = self.client.list_invoices('owner', '2026-10-01', '2026-10-31', page=2)
            self.assertFalse(result['pending'])
            self.assertIsNone(result['next_page'])

    def test_singleton_and_empty_list(self):
        singleton = page([row()])
        singleton['invoices']['invoice'] = row()
        with patch.object(m, '_read', return_value=singleton):
            self.assertEqual(len(self.client.list_invoices('owner', '2026-10-01', '2026-10-31')['invoices']), 1)
        with patch.object(m, '_read', return_value={'invoices': {'@total': '0'}}):
            self.assertEqual(self.client.list_invoices('owner', '2026-10-01', '2026-10-31')['invoices'], [])

    def test_malformed_or_incomplete_page_never_reported_complete(self):
        wrong_page = page([row()]); wrong_page['invoices']['@page'] = '2'
        no_total = page([row()]); del no_total['invoices']['@total']
        cases = [[], {}, wrong_page, no_total, page([row()], total=26), page([row(), row()]),
                 page([row('2'), row('1')]), page([row(date='2026-09-30')]),
                 page([row(status='PAID')])]
        for payload in cases:
            with self.subTest(payload=payload), patch.object(m, '_read', return_value=payload), self.assertRaises(m.BillomatError):
                self.client.list_invoices('owner', '2026-10-01', '2026-10-31', status='OPEN')

    def test_invalid_request_and_identifier_never_contact_provider(self):
        with patch.object(m, '_read') as read:
            for args in [('2026-10-02', '2026-10-01', 1, ''), ('2026-02-30', '2026-10-31', 1, ''),
                         ('2024-01-01', '2026-10-31', 1, ''), ('2026-10-01', '2026-10-31', True, ''),
                         ('2026-10-01', '2026-10-31', 1, 'OPEN,../')]:
                with self.assertRaises(m.BillomatError): self.client.list_invoices('owner', *args)
            for ident in ['../clients', 'https://evil.example', '0', True, '-1', '1?x=2']:
                with self.assertRaises(m.BillomatError): self.client.get_pdf('owner', ident)
            read.assert_not_called()

    def test_invoice_metadata_amount_and_identity_validation(self):
        for values in [{'currency_code': ''}, {'status': []}, {'status': 'UNKNOWN'}, {'total_net': 0.1},
                       {'total_gross': 'NaN'}, {'open_amount': True}, {'total_net': '1e999'},
                       {'total_net': '0.0000000000001'}, {'invoice_number': ''}]:
            with self.subTest(values=values), self.assertRaises(m.BillomatError): m._invoice(row(**values))
        result = m._invoice(row(status='DRAFT', invoice_number='', paid_amount=None))
        self.assertIsNone(result['paid_amount'])
        self.assertTrue(result['warnings'])
        with patch.object(m, '_read', return_value={'invoice': row('2')}), self.assertRaises(m.BillomatError):
            self.client.get_invoice('owner', '1')
        with patch.object(m, '_read', return_value={'invoice': dict(row(), customerportal_url='SECRET', address='PRIVATE')}):
            result = self.client.get_invoice('owner', '1')
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertNotIn('PRIVATE', json.dumps(result))

    def transport(self, status=200, body=b'{}', content_type='application/json', length=None):
        connection = MagicMock()
        result = connection.getresponse.return_value
        result.status = status
        result.getheader.side_effect = lambda key, default=None: content_type if key == 'Content-Type' else length
        result.read1.side_effect = [body, b'']
        return connection

    def test_transport_is_pinned_get_no_redirects_and_safe_errors(self):
        for status, body, ctype, length in [(302, b'', 'application/json', None),
                (401, KEY.encode(), 'application/json', None), (200, b'{}', 'text/html', None),
                (200, b'{}', 'application/json', str(m.MAX_JSON+1)), (200, b'{}', 'application/json', '99'),
                (200, b'{"x":1,"x":2}', 'application/json', None)]:
            connection = self.transport(status, body, ctype, length)
            with patch.object(m.http.client, 'HTTPSConnection', return_value=connection) as factory:
                with self.assertRaises(m.BillomatError) as caught:
                    m._read('example-company.billomat.net', KEY, '/api/invoices', {'page': 1})
                self.assertNotIn(KEY, str(caught.exception))
                self.assertEqual(factory.call_args.args, ('example-company.billomat.net', 443))
                self.assertEqual(connection.request.call_args.args[0], 'GET')
                self.assertEqual(connection.request.call_count, 1)
                connection.close.assert_called_once()

    def test_transport_decodes_decimal_and_pdf_is_bounded_binary(self):
        connection = self.transport(body=b'{"total_gross":119.123456789012}')
        with patch.object(m.http.client, 'HTTPSConnection', return_value=connection):
            payload = m._read('example-company.billomat.net', KEY, '/api/invoices/1', {})
            self.assertEqual(payload['total_gross'], Decimal('119.123456789012'))
        pdf = b'%PDF-1.7\ncontent\n%%EOF\n'
        connection = self.transport(body=pdf, content_type='application/pdf', length=str(len(pdf)))
        with patch.object(m.http.client, 'HTTPSConnection', return_value=connection):
            self.assertEqual(self.client.get_pdf('owner', '1'), pdf)
            self.assertEqual(connection.request.call_args.args[1], '/api/invoices/1/pdf?format=pdf')
        for body in [b'<script>x</script>', b'%PDF-1.7 truncated']:
            connection = self.transport(body=body, content_type='application/pdf')
            with patch.object(m.http.client, 'HTTPSConnection', return_value=connection), self.assertRaises(m.BillomatError):
                self.client.get_pdf('owner', '1')


if __name__ == '__main__':
    unittest.main()
