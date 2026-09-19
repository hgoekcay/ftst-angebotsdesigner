import logging

import requests

log = logging.getLogger("ftst.billomat")


class CustomerWriteUncertain(RuntimeError):
    """The server may have committed. Never automatically retry this write."""


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

    def list_offers(self, search="", page=1):
        params = {"format": "json", "per_page": 30, "page": page, "order_by": "date DESC, id DESC"}
        if search:
            params["offer_number"] = search
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
