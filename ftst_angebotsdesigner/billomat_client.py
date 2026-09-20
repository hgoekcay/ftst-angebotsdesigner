import logging
import json
import re

import requests

log = logging.getLogger("ftst.billomat")


class CustomerWriteUncertain(RuntimeError):
    """The server may have committed. Never automatically retry this write."""


class OfferWriteUncertain(RuntimeError):
    """The POST may have committed; reconcile by the persisted marker, never retry."""


class OfferReadError(RuntimeError):
    """Bounded verification failed without exposing API bodies or credentials."""


class BillomatClient:
    def __init__(self, billomat_id, api_key):
        self.billomat_id = (billomat_id or "").strip()
        self.base = f"https://{self.billomat_id}.billomat.net/api"
        self.headers = {
            "X-BillomatApiKey": (api_key or "").strip(),
            "Accept": "application/json",
            "User-Agent": "FTST-AngebotsDesigner/0.1.8",
        }

    def _get(self, path, params=None):
        url = self.base + path
        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=20)
        except requests.RequestException as exc:
            log.exception("Billomat request failed: %s %s -> %s", path, params or {}, exc)
            raise RuntimeError(f"Billomat-Verbindung fehlgeschlagen: {type(exc).__name__}: {exc}") from exc

        if not r.ok:
            body = (r.text or "").replace("\n", " ").replace("\r", " ")[:500]
            log.error("Billomat HTTP %s for %s params=%s body=%s", r.status_code, path, params or {}, body)
            raise RuntimeError(f"Billomat API HTTP {r.status_code}: {body}")

        try:
            return r.json()
        except ValueError as exc:
            body = (r.text or "").replace("\n", " ").replace("\r", " ")[:500]
            log.error("Billomat returned non-JSON for %s: content_type=%s body=%s", path, r.headers.get("content-type"), body)
            raise RuntimeError(f"Billomat lieferte kein JSON (Content-Type: {r.headers.get('content-type', '-')}). Antwort: {body}") from exc

    @staticmethod
    def _unwrap(obj, key):
        return obj.get(key, obj) if isinstance(obj, dict) else obj

    def list_offers(self, search="", page=1, status=""):
        params = {"format": "json", "per_page": 30, "page": page, "order_by": "date DESC, id DESC"}
        if search:
            params["offer_number"] = search
        if status:
            if status not in {'DRAFT', 'OPEN', 'WON', 'LOST', 'CANCELED', 'CLEARED'}:
                raise ValueError('Ungültiger Angebotsstatus.')
            params['status'] = status
        data = self._get("/offers", params)
        if not isinstance(data, dict) or 'offers' not in data:
            raise RuntimeError('Ungültige Angebotsliste von Billomat.')
        offers = self._unwrap(data, "offers")
        if isinstance(offers, dict):
            offers = offers.get("offer", [])
        if not isinstance(offers, list):
            offers = [offers] if offers else []
        if len(offers) > 30 or any(not isinstance(row, dict) or not str(row.get('id', '')).isdigit() for row in offers):
            raise RuntimeError('Ungültige Angebotsliste von Billomat.')
        return offers

    def get_offer(self, offer_id):
        return self._unwrap(self._get(f"/offers/{offer_id}", {"format": "json"}), "offer")

    def get_offer_items(self, offer_id):
        data = self._get("/offer-items", {"format": "json", "offer_id": offer_id, "per_page": 100})
        items = self._unwrap(data, "offer-items")
        if isinstance(items, dict):
            items = items.get("offer-item", [])
        return items if isinstance(items, list) else ([items] if items else [])

    def get_client(self, client_id):
        if not client_id:
            return {}
        return self._unwrap(self._get(f"/clients/{client_id}", {"format": "json"}), "client")

    def create_client(self, fields):
        try:
            response = requests.post(self.base + '/clients', headers=dict(self.headers, **{'Content-Type':'application/json'}),
                                     json={'client': fields}, timeout=(10, 30), allow_redirects=False)
            if response.status_code != 201:
                raise CustomerWriteUncertain('Billomat hat die Anlage nicht eindeutig bestätigt. Kundenliste prüfen; nicht erneut anlegen.')
            client = self._unwrap(response.json(), 'client')
            if not isinstance(client, dict) or not str(client.get('id', '')).isdigit():
                raise ValueError
            return client
        except (requests.RequestException, ValueError, TypeError) as exc:
            raise CustomerWriteUncertain('Ergebnis der Kundenanlage unklar. Vor jeder weiteren Anlage die Billomat-Kundenliste prüfen.') from exc

    def get_full_offer(self, offer_id):
        offer = self.get_offer(offer_id)
        offer["items"] = self.get_offer_items(offer_id)
        offer["client"] = self.get_client(offer.get("client_id"))
        return offer

    @staticmethod
    def _offer_id(value):
        value = str(value)
        if not re.fullmatch(r'[1-9][0-9]{0,19}', value):
            raise ValueError('Ungültige Billomat-ID.')
        return value

    def _offer_request(self, method, path, *, payload=None, params=None):
        """Separate hardened transport; no retries, redirects, proxy env or raw errors."""
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', self.billomat_id):
            raise ValueError('Ungültige Billomat-Kennung.')
        key = self.headers.get('X-BillomatApiKey', '')
        if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError('Billomat-Zugang ist nicht eingerichtet.')
        error = OfferWriteUncertain if method == 'POST' else OfferReadError
        message = ('Ergebnis der Angebotsanlage unklar. Vor einer weiteren Anlage den gespeicherten Vorgang abgleichen.'
                   if method == 'POST' else 'Billomat-Angebot konnte nicht vollständig geprüft werden.')
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.request(method, self.base + path,
                    headers=dict(self.headers, **{'Content-Type': 'application/json'}),
                    json=payload, params=dict(params or {}, format='json'),
                    timeout=(5, 30), allow_redirects=False, verify=True, stream=True)
                with response:
                    if response.status_code != (201 if method == 'POST' else 200):
                        raise error(message)
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            raise error(message)
                        chunks.append(chunk)
                    result = json.loads(b''.join(chunks))
                    if not isinstance(result, dict):
                        raise error(message)
                    return result
        except (requests.RequestException, ValueError, TypeError):
            raise error(message) from None

    @staticmethod
    def validate_offer_payload(payload):
        """Pure preflight: return a detached JSON body or raise ValueError, no I/O.

        Call before durably claiming a transfer; create_offer_draft repeats it.
        """
        allowed = {'client_id', 'date', 'title', 'label', 'intro', 'note', 'reduction',
                   'currency_code', 'net_gross', 'validity_days', 'validity_date', 'offer-items'}
        item_fields = {'article_id', 'unit', 'quantity', 'unit_price', 'tax_name',
                       'tax_rate', 'title', 'description', 'reduction', 'optional'}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError('Ungültige Felder für die Angebotsanlage.')
        BillomatClient._offer_id(payload.get('client_id'))
        nested = payload.get('offer-items')
        rows = nested.get('offer-item') if isinstance(nested, dict) and set(nested) == {'offer-item'} else None
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError('Ein Angebot benötigt 1 bis 100 Positionen.')
        if any(not isinstance(row, dict) or set(row) - item_fields for row in rows):
            raise ValueError('Ungültige Angebotsposition.')
        if payload.get('net_gross') != 'NET' or not re.fullmatch(r'[A-Z]{3}', str(payload.get('currency_code', ''))):
            raise ValueError('Explizite Nettopreise und Währung sind erforderlich.')
        try:
            encoded = json.dumps({'offer': payload}, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError):
            raise ValueError('Ungültige Angebotsdaten.') from None
        if len(encoded) > 256 * 1024:
            raise ValueError('Angebotsdaten sind zu umfangreich.')
        return json.loads(encoded)

    def create_offer_draft(self, payload):
        """One POST with embedded items. The server creates DRAFT; never complete/send.

        Documented at billomat.com/api/angebote/ and /angebote/positionen/.
        The caller must durably claim its operation before invoking this method.
        """
        body = self.validate_offer_payload(payload)
        result = self._offer_request('POST', '/offers', payload=body)
        offer = result.get('offer')
        if not isinstance(offer, dict) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(offer.get('id', ''))):
            raise OfferWriteUncertain('Billomat hat keine eindeutige Angebots-ID bestätigt. Vorgang abgleichen.')
        # Sparse creation responses are documented; the caller must read back.
        if offer.get('status') not in (None, '', 'DRAFT'):
            raise OfferWriteUncertain('Billomat hat den Entwurfsstatus nicht bestätigt. Vorgang abgleichen.')
        return offer

    def _offer_collection(self, plural, singular, params, maximum=500):
        rows, seen = [], set()
        for page in range(1, maximum // 100 + 2):
            result = self._offer_request('GET', '/' + plural,
                params=dict(params, per_page=100, page=page))
            if plural not in result:
                raise OfferReadError('Billomat-Liste ist unvollständig.')
            container = result[plural]
            if isinstance(container, list):
                batch, total = container, None
            elif isinstance(container, dict):
                if singular not in container and container and str(container.get('@total', container.get('total'))) != '0':
                    raise OfferReadError('Billomat-Liste ist unvollständig.')
                batch = container.get(singular, [])
                batch = batch if isinstance(batch, list) else ([batch] if batch else [])
                total = container.get('@total', container.get('total'))
            else:
                raise OfferReadError('Ungültige Billomat-Liste.')
            if len(batch) > 100:
                raise OfferReadError('Billomat-Liste ist zu umfangreich.')
            for row in batch:
                if not isinstance(row, dict):
                    raise OfferReadError('Ungültige Billomat-Liste.')
                identifier = str(row.get('id', ''))
                if not re.fullmatch(r'[1-9][0-9]{0,19}', identifier) or identifier in seen:
                    raise OfferReadError('Billomat-Liste ist unvollständig oder wiederholt Positionen.')
                seen.add(identifier)
                rows.append(row)
            if len(rows) > maximum:
                raise OfferReadError('Billomat-Liste ist zu umfangreich.')
            if total is not None:
                if not re.fullmatch(r'[0-9]{1,8}', str(total)) or int(total) < len(rows) or int(total) > maximum:
                    raise OfferReadError('Billomat-Liste ist unvollständig oder zu umfangreich.')
                if int(total) == len(rows):
                    return rows
                if not batch:
                    raise OfferReadError('Billomat-Liste ist unvollständig.')
            elif len(batch) < 100:
                return rows
        raise OfferReadError('Billomat-Liste ist unvollständig.')

    def get_offer_for_verification(self, offer_id):
        offer_id = self._offer_id(offer_id)
        data = self._offer_request('GET', '/offers/' + offer_id)
        offer = data.get('offer')
        if not isinstance(offer, dict) or str(offer.get('id')) != offer_id:
            raise OfferReadError('Billomat hat ein anderes Angebot zurückgegeben.')
        items = self._offer_collection('offer-items', 'offer-item', {'offer_id': offer_id}, maximum=100)
        if any(str(item.get('offer_id')) != offer_id for item in items):
            raise OfferReadError('Billomat-Positionen gehören nicht zum Angebot.')
        return dict(offer, items=items)

    def find_offers_by_reference(self, marker, client_id):
        """Read-only recovery candidates, including a draft subsequently completed.

        label search is substring based; exact matching here never authorizes retry.
        """
        client_id = self._offer_id(client_id)
        if not isinstance(marker, str) or not 1 <= len(marker) <= 200 or marker != marker.strip():
            raise ValueError('Ungültige Vorgangskennung.')
        rows = self._offer_collection('offers', 'offer', {'client_id': client_id, 'label': marker})
        return [row for row in rows if row.get('label') == marker and str(row.get('client_id')) == client_id]

    def collection(self, plural, singular, params=None):
        """Read a complete catalog or fail; never silently price from a partial list."""
        rows, seen = [], set()
        for page in range(1, 101):
            data = self._unwrap(self._get('/'+plural, dict(params or {}, format='json', per_page=100, page=page)), plural)
            batch = data.get(singular, []) if isinstance(data, dict) else data
            batch = batch if isinstance(batch, list) else ([batch] if batch else [])
            if not batch:
                return rows
            for row in batch:
                if not isinstance(row, dict) or not str(row.get('id', '')).isdigit() or str(row['id']) in seen:
                    raise RuntimeError('Billomat-Katalog unvollständig oder ungültig.')
                seen.add(str(row['id']))
                rows.append(row)
            total = data.get('@total', data.get('total')) if isinstance(data, dict) else None
            if total is not None and len(rows) >= int(total):
                return rows
        raise RuntimeError('Billomat-Katalog zu groß. Bitte Suche eingrenzen.')

    def draft_catalog(self):
        return {
            'articles': self.collection('articles', 'article'),
            'clients': self.collection('clients', 'client'),
            'taxes': self.collection('taxes', 'tax'),
            'units': self.collection('units', 'unit'),
            'settings': self._unwrap(self._get('/settings', {'format':'json'}), 'settings'),
        }
