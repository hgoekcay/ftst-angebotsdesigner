import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

MODULE_PATH=Path(__file__).resolve().parents[1]/'ftst_angebotsdesigner/website_portal_client.py'
spec=importlib.util.spec_from_file_location('portal_client',MODULE_PATH)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PortalClientTests(unittest.TestCase):
    def setUp(self):
        self.transport=Mock()
        response=Mock(status_code=201,content=b'{}')
        response.json.return_value={'proposal_id':'12345678-1234-1234-1234-123456789abc'}
        self.transport.request.return_value=response
        self.client=module.PortalClient('https://portal.example','a'*64,site_service_token='dispatch-private',session=self.transport)
    def test_original_pdf_and_snapshot_are_transmitted_unchanged(self):
        snapshot={'schema_version':'ftst.customer-proposal.v1','approved_for_customer':True,'images':[]}
        pdf=b'%PDF-original-revision'
        self.client.publish(snapshot,pdf)
        args,kw=self.transport.request.call_args
        self.assertEqual(args,('POST','https://portal.example/api/internal/proposals'))
        self.assertEqual(json.loads(kw['data']['snapshot']),snapshot)
        self.assertEqual(kw['files'][0][1][1],pdf)
        self.assertFalse(kw['allow_redirects'])
        self.assertEqual(kw['headers']['OAI-Sites-Authorization'],'Bearer dispatch-private')
    def test_unapproved_snapshots_and_nonpdf_are_blocked_before_network(self):
        for s,pdf in [({},b'%PDF-'),({'schema_version':'ftst.customer-proposal.v1','approved_for_customer':False},b'%PDF-'),({'schema_version':'ftst.customer-proposal.v1','approved_for_customer':True},b'not-pdf')]:
            with self.assertRaises(ValueError):self.client.publish(s,pdf)
        self.transport.request.assert_not_called()
    def test_link_creation_revoke_and_poll_are_separate_operations(self):
        self.client.create_link('12345678-1234-1234-1234-123456789abc')
        self.assertEqual(self.transport.request.call_args.kwargs['json'],{'expires_in_days':7})
        self.client.revoke('b'*64)
        self.assertTrue(self.transport.request.call_args.args[1].endswith('/revoke'))
        self.client.responses(5)
        self.assertTrue(self.transport.request.call_args.args[1].endswith('after=5'))
    def test_no_redirects_automatic_retries_or_error_secrets(self):
        self.transport.request.return_value.status_code=302
        with self.assertRaises(module.PortalError) as caught:self.client.responses()
        self.assertNotIn('a'*64,str(caught.exception))
        self.assertEqual(self.transport.request.call_count,1)
        for origin in ['http://portal.example','https://user:pass@portal.example','https://portal.example/path','https://portal.example#secret']:
            with self.assertRaises(ValueError):module.PortalClient(origin,'a'*64)
    def test_images_must_match_explicitly_approved_descriptors(self):
        snapshot={'schema_version':'ftst.customer-proposal.v1','approved_for_customer':True,'images':[{'id':'approved'}]}
        with self.assertRaises(ValueError):self.client.publish(snapshot,b'%PDF-',{'other':b'image'})
        self.transport.request.assert_not_called()

if __name__=='__main__':unittest.main()
