import logging

import requests

log = logging.getLogger("ftst.billomat")


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

    def list_offers(self, search=""):
        params = {"format": "json", "per_page": 1000, "order_by": "date DESC"}
        if search:
            params["offer_number"] = search
        data = self._get("/offers", params)
        offers = self._unwrap(data, "offers")
        if isinstance(offers, dict):
            offers = offers.get("offer", [])
        if not isinstance(offers, list):
            offers = [offers] if offers else []
        return sorted(offers, key=lambda x: (str(x.get("date", "")), str(x.get("offer_number") or x.get("number") or "")), reverse=True)

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

    def get_full_offer(self, offer_id):
        offer = self.get_offer(offer_id)
        offer["items"] = self.get_offer_items(offer_id)
        offer["client"] = self.get_client(offer.get("client_id"))
        return offer
