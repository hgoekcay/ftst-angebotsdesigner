import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[2] / 'ftst_atlas'))

spec = importlib.util.spec_from_file_location('bookkeeping',Path(__file__).parents[2] / 'ftst_atlas' / 'bookkeeping.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

XML = b'''<?xml version="1.0"?><Invoice xmlns="urn:invoice" xmlns:c="urn:common"><c:ID>R-123</c:ID><c:IssueDate>2026-10-02</c:IssueDate><c:DocumentCurrencyCode>EUR</c:DocumentCurrencyCode><c:AccountingSupplierParty><c:Party><c:PartyLegalEntity><c:RegistrationName>Example GmbH</c:RegistrationName></c:PartyLegalEntity></c:Party></c:AccountingSupplierParty><c:TaxTotal><c:TaxAmount>19.00</c:TaxAmount></c:TaxTotal><c:LegalMonetaryTotal><c:TaxExclusiveAmount>100.00</c:TaxExclusiveAmount><c:TaxInclusiveAmount>119.00</c:TaxInclusiveAmount></c:LegalMonetaryTotal></Invoice>'''
PNG = b'\x89PNG\r\n\x1a\nsynthetic'


class BookkeepingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        def db(): return sqlite3.connect(self.root / 'test.sqlite3')
        self.db = db
        self.store = module.Bookkeeping(db,self.root)
    def tearDown(self): self.tmp.cleanup()
    def invoice(self, **overrides):
        data = {'id':'42','supplier':'Example Client','invoice_number':'INV-42','invoice_date':'2026-10-02','currency':'EUR','net':'100.00','tax':'19.00','gross':'119.00','payment_status':'unknown'}
        data.update(overrides)
        return data
    def xml(self,user='alice',source=None):
        return self.store.ingest_document(user,XML,'../../invoice.xml','application/xml',source or {'provider':'upload'})

    def test_xml_requires_manual_review_and_original_preserved(self):
        record = self.xml()
        self.assertEqual(record['fields']['gross'],'119.00')
        self.assertEqual(record['fields']['supplier'],'Example GmbH')
        self.assertEqual(record['fields']['payment_status'],'unknown')
        self.assertEqual(record['status'],'needs_review')
        self.assertEqual(record['issues'],[])
        self.assertEqual(record['filename'],'invoice.xml')
        self.assertEqual(self.store.get_document('alice',record['id'])[0],XML)
        checked = self.store.review('alice',record['id'],{'reviewed':True})
        self.assertEqual(checked['status'],'reviewed')
        self.assertEqual(checked['audit'][-1]['action'],'review')
        self.assertEqual(self.store.get_document('alice',record['id'])[0],XML)

    def test_dedup_and_owner_isolation(self):
        first = self.xml(source={'type':'mail','message_uid':'1','account_id':'primary'})
        second = self.xml(source={'provider':'mail','message_uid':'2','account_id':'other'})
        self.assertEqual(first['id'],second['id'])
        self.assertTrue(second['duplicate'])
        self.assertEqual(len(second['sources']),2)
        self.assertEqual(self.store.list('bob'),[])
        self.assertIsNone(self.store.get('bob',first['id']))
        self.assertIsNone(self.store.get_document('bob',first['id']))
        with self.assertRaises(module.BookkeepingError): self.store.review('bob',first['id'],{'reviewed':False})
        self.assertNotEqual(self.xml('bob')['id'],first['id'])

    def test_input_guards_and_xml_entity_rejection(self):
        for data in (b'<!DOCTYPE a [<!ENTITY x "x">]><a>&x;</a>',b'<!ENTITY x SYSTEM "file:///etc/passwd"><a/>',b'\xff\xfe<\x00a\x00>\x00'):
            with self.assertRaises(module.BookkeepingError): self.store.ingest_document('alice',data,'x.xml','application/xml',{'provider':'upload'})
        with self.assertRaises(module.BookkeepingError): self.store.ingest_document('alice',b'x'*(module.MAX_FILE+1),'x.pdf','application/pdf',{'provider':'upload'})
        with self.assertRaises(module.BookkeepingError): self.store.ingest_document('alice',b'notpdf','x.pdf','application/pdf',{'provider':'upload'})
        with self.assertRaises(module.BookkeepingError): self.xml(source={'provider':'mail','password':'secret'})
        with self.assertRaises(module.BookkeepingError): self.xml(source={'provider':'mail','reference':'https://example.com/?token=x'})
        with self.assertRaises(module.BookkeepingError): self.store.list('')

    def test_review_exact_amounts_and_invalidation(self):
        record = self.xml()
        with self.assertRaises(module.BookkeepingError): self.store.review('alice',record['id'],{'net':100.0})
        with self.assertRaises(module.BookkeepingError): self.store.review('alice',record['id'],{'gross':'120.00','reviewed':True})
        self.store.review('alice',record['id'],{'reviewed':True})
        changed = self.store.review('alice',record['id'],{'supplier':'Corrected'})
        self.assertFalse(changed['reviewed'])
        self.assertEqual(changed['audit'][-1]['before']['reviewed'],True)
        blank = self.store.review('alice',record['id'],{'tax':'','reviewed':False})
        self.assertIn('Feld fehlt: tax',blank['issues'])

    def test_images_stored_without_invented_ocr(self):
        record = self.store.ingest_document('alice',PNG,'scan.png','image/png',{'provider':'upload'})
        self.assertEqual(record['fields']['gross'],'')
        self.assertIn('OCR',record['extraction_notes'][0])
        self.assertEqual(self.store.get_document('alice',record['id'])[0],PNG)

    def test_tiff_preserved_without_ocr(self):
        data=b'II*\x00synthetic'
        record=self.store.ingest_document('alice',data,'scan.tiff','image/tiff',{'provider':'mail','reference':'tiff1'})
        self.assertEqual(self.store.get_document('alice',record['id'])[0],data)
        self.assertIn('OCR',record['extraction_notes'][0])

    def test_pdf_child_bounded_and_failure_preserves_original(self):
        with patch.object(module.subprocess,'run',side_effect=module.subprocess.TimeoutExpired('python',15)) as mocked:
            data=b'%PDF-1.4\nsynthetic'
            record=self.store.ingest_document('alice',data,'invoice.pdf','application/pdf',{'provider':'upload'})
            self.assertEqual(self.store.get_document('alice',record['id'])[0],data)
            self.assertEqual(record['status'],'needs_review')
            self.assertEqual(mocked.call_args.kwargs['timeout'],15)
            self.assertEqual(mocked.call_args.args[0][1],'-I')
            self.assertIn('RLIMIT_AS',mocked.call_args.args[0][3])
            self.assertEqual(mocked.call_args.kwargs['stderr'],module.subprocess.DEVNULL)

    def test_pdf_labeled_extract_no_derived_tax(self):
        result=module._extract_text('Lieferant: Example GmbH\nRechnungsnummer: R-3\nRechnungsdatum: 02.10.2026\nNettobetrag: 1.234,56 EUR\nGesamtbetrag: 1.469,13 EUR\n')
        self.assertEqual(result['net'],'1234.56')
        self.assertNotIn('tax',result)
        self.assertNotIn('currency',result)
        self.assertEqual(result['invoice_date'],'2026-10-02')

    def test_billomat_snapshot_refresh_and_original_association(self):
        first=self.store.ingest_billomat('alice',self.invoice())
        self.assertFalse(first['duplicate'])
        self.assertEqual(first['direction'],'outgoing')
        self.assertTrue(self.store.ingest_billomat('alice',self.invoice())['duplicate'])
        self.store.review('alice',first['id'],{'reviewed':True})
        pdf=b'%PDF-1.4\noriginal'
        self.store.attach_original('alice',first['id'],pdf,'billomat.pdf')
        changed=self.store.ingest_billomat('alice',self.invoice(payment_status='paid'))
        self.assertEqual(changed['id'],first['id'])
        self.assertFalse(changed['duplicate'])
        self.assertFalse(changed['reviewed'])
        self.assertEqual(len(changed['snapshots']),2)
        self.assertEqual(self.store.get_document('alice',first['id'])[0],pdf)
        self.assertEqual(changed['audit'][-1]['action'],'source_refresh')
        with self.assertRaises(module.BookkeepingError): self.store.attach_original('bob',first['id'],pdf,'x.pdf')
        with self.assertRaises(module.BookkeepingError): self.store.attach_original('alice',first['id'],b'%PDF-different','x.pdf')

    def test_export_formula_guard_unknowns_and_versions(self):
        record=self.store.ingest_billomat('alice',self.invoice(supplier=' =HYPERLINK("bad")'))
        self.store.attach_original('alice',record['id'],b'%PDF-1.4\noriginal','original.pdf')
        self.store.ingest_billomat('alice',self.invoice(supplier=' =HYPERLINK("bad")',payment_status='paid'))
        self.store.ingest_document('alice',PNG,'undated.png','image/png',{'provider':'upload'})
        self.store.ingest_billomat('alice',self.invoice(id='43',invoice_date='2026-09-01'))
        with zipfile.ZipFile(io.BytesIO(self.store.export('alice','2026-10'))) as archive:
            csv=archive.read('belege.csv').decode('utf-8-sig')
            self.assertIn("'=HYPERLINK",csv)
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(len(manifest['records']),2)
            bridge=json.loads(archive.read('ai-bookkeeping.documents.json'))
            self.assertEqual(bridge['schema'],'documents/1')
            self.assertTrue(all(d['review_open'] for d in bridge['documents']))
            self.assertTrue(bridge['notes'])
            billomat=next(r for r in manifest['records'] if r['source']['provider']=='billomat')
            self.assertEqual(len(billomat['snapshot_files']),2)
            self.assertEqual(archive.read(billomat['original']),b'%PDF-1.4\noriginal')
            self.assertEqual(len(json.loads(archive.read('ungeklaert.json'))),2)
        with self.assertRaises(module.BookkeepingError): self.store.export('alice','2026-13')
        with zipfile.ZipFile(io.BytesIO(self.store.export('bob','2026-10'))) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json'))['records'],[])

    def test_source_refresh_preserves_manual_missing_fields(self):
        record=self.store.ingest_billomat('alice',self.invoice(supplier='',tax='',source_status='OPEN',source_open_amount='119.00'))
        self.store.review('alice',record['id'],{'supplier':'Manually checked party','tax':'19.00','reviewed':True})
        changed=self.store.ingest_billomat('alice',self.invoice(supplier='',tax='',source_status='PAID',source_open_amount='0.00',payment_status='paid'))
        self.assertEqual(changed['fields']['supplier'],'Manually checked party')
        self.assertEqual(changed['fields']['tax'],'19.00')
        self.assertEqual(changed['source_open_amount'],'0.00')
        self.assertFalse(changed['reviewed'])

    def test_source_cancellation_and_open_amount_not_editable(self):
        record=self.store.ingest_billomat('alice',self.invoice(source_status='OPEN',source_open_amount='119.00'))
        self.assertEqual(record['source_open_amount'],'119.00')
        with self.assertRaises(module.BookkeepingError): self.store.review('alice',record['id'],{'source_status':'PAID'})
        with self.assertRaises(module.BookkeepingError): self.store.review('alice',record['id'],{'source_open_amount':'0.00'})
        canceled=self.store.ingest_billomat('alice',self.invoice(source_status='CANCELED',source_open_amount='0.00'))
        self.assertEqual(canceled['id'],record['id'])
        self.assertEqual(canceled['status'],'canceled')
        self.assertTrue(canceled['canceled'])
        self.assertIn('Storno',canceled['issues'][0])
        with self.assertRaises(module.BookkeepingError): self.store.review('alice',record['id'],{'reviewed':True})

    def test_employee_source_metadata_bounded(self):
        record=self.store.ingest_document('alice',PNG,'scan.png','image/png',{'provider':'employee','reference':'receipt1','access_id':'access1','label':'Team','project':'P1','note':'Beleg zur Prüfung'})
        self.assertEqual(record['source']['type'],'employee')
        with self.assertRaises(module.BookkeepingError): self.store.ingest_document('alice',PNG,'scan.png','image/png',{'provider':'employee','note':'a'*501})

    def test_month_export_not_truncated_by_ui_list_limit(self):
        old=self.store.ingest_billomat('alice',self.invoice(id='old',invoice_date='2026-01-02'))
        self.store.ingest_billomat('alice',self.invoice(id='new',invoice_date='2026-10-02'))
        with patch.object(module,'MAX_RECORDS',1):
            self.assertEqual(len(self.store.list('alice')),1)
            with zipfile.ZipFile(io.BytesIO(self.store.export('alice','2026-01'))) as archive:
                records=json.loads(archive.read('manifest.json'))['records']
                self.assertEqual([r['id'] for r in records],[old['id']])
        with patch.object(module,'MAX_EXPORT_FILES',1):
            self.store.ingest_document('alice',PNG,'undated.png','image/png',{'provider':'upload'})
            with self.assertRaises(module.BookkeepingError): self.store.export('alice','2026-01')

    def test_tampered_original_detected(self):
        record=self.xml()
        with self.db() as db: path=db.execute('SELECT original_path FROM atlas_bookkeeping WHERE id=?',(record['id'],)).fetchone()[0]
        (self.store.root/path).write_bytes(b'tampered')
        with self.assertRaises(module.BookkeepingError): self.store.get_document('alice',record['id'])

if __name__=='__main__': unittest.main()
