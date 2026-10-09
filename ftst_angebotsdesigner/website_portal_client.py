"""Server-only transport for approved FTST customer snapshots and original PDFs.

No Flask routes, Billomat writes, release decision, email, or customer acceptance.
The caller must create/approve an allowlisted snapshot of the exact PDF revision.
"""
import json
from urllib.parse import urlsplit
import requests


class PortalError(RuntimeError):
    """Sanitized portal failure; no credentials or customer link in the message."""


class PortalClient:
    def __init__(self, base_url, publish_secret, *, site_service_token=None, session=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('Portal requires an HTTPS origin without a path or credentials.')
        if not isinstance(publish_secret, str) or len(publish_secret) < 32:
            raise ValueError('Portal publishing credential is not configured.')
        self.base_url = base_url.rstrip('/')
        self._session = session or requests.Session()
        self._headers = {'Authorization': 'Bearer ' + publish_secret}
        if site_service_token:
            # Dispatch credential is separate from the portal publishing credential.
            self._headers['OAI-Sites-Authorization'] = 'Bearer ' + site_service_token

    def _request(self, method, path, **kwargs):
        try:
            response = self._session.request(method, self.base_url + path,
                headers=self._headers, timeout=(5, 45), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise PortalError('Customer portal could not be reached; no automatic retry.') from None
        if response.status_code not in (200, 201):
            raise PortalError(f'Customer portal returned HTTP {response.status_code}; review before retrying.')
        if len(response.content) > 8 * 1024 * 1024:
            raise PortalError('Customer portal response exceeded the size limit.')
        try:
            result = response.json()
        except ValueError:
            raise PortalError('Customer portal returned an invalid response.') from None
        if not isinstance(result, dict):
            raise PortalError('Customer portal returned an invalid response.')
        return result

    def publish(self, snapshot, original_pdf, images=None):
        if (not isinstance(snapshot, dict) or snapshot.get('schema_version') != 'ftst.customer-proposal.v1'
                or snapshot.get('approved_for_customer') is not True):
            raise ValueError('An explicitly approved customer snapshot is required.')
        if not isinstance(original_pdf, bytes) or not original_pdf.startswith(b'%PDF-'):
            raise ValueError('Original PDF bytes are required.')
        if len(original_pdf) > 8 * 1024 * 1024:
            raise ValueError('Original PDF exceeds the portal limit.')
        images = images or {}
        descriptors = snapshot.get('images', [])
        if len(descriptors) > 4 or set(images) != {x['id'] for x in descriptors}:
            raise ValueError('Supply exactly the approved images, at most four.')
        files = [('pdf', ('original.pdf', original_pdf, 'application/pdf'))]
        for image_id, content in images.items():
            if not isinstance(content, bytes) or len(content) > 2 * 1024 * 1024:
                raise ValueError('Invalid approved image bytes.')
            files.append(('image:' + image_id, ('image', content, 'application/octet-stream')))
        return self._request('POST', '/api/internal/proposals',
            data={'snapshot': json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))}, files=files)

    def create_link(self, proposal_id, expires_in_days=7):
        self._proposal_id(proposal_id)
        if type(expires_in_days) is not int or not 1 <= expires_in_days <= 30:
            raise ValueError('Link lifetime must be 1–30 days.')
        # A lost response is not retried automatically: the token is only returned once.
        return self._request('POST', f'/api/internal/proposals/{proposal_id}/links',
            json={'expires_in_days': expires_in_days})

    def revoke(self, link_id):
        if (not isinstance(link_id, str) or len(link_id) != 64
                or any(c not in '0123456789abcdef' for c in link_id)):
            raise ValueError('Invalid portal link ID.')
        return self._request('POST', f'/api/internal/links/{link_id}/revoke')

    def responses(self, after=0):
        if type(after) is not int or not 0 <= after < 10**12:
            raise ValueError('Invalid response cursor.')
        return self._request('GET', f'/api/internal/responses?after={after}')

    @staticmethod
    def _proposal_id(value):
        from uuid import UUID
        try:
            if str(UUID(value)) != value:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid portal proposal ID.') from None
