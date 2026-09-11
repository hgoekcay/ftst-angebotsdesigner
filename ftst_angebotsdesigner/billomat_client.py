import requests

class BillomatClient:
    def __init__(self, billomat_id, api_key):
        self.base = f"https://{billomat_id}.billomat.net/api"
        self.headers = {"X-BillomatApiKey": api_key, "Accept": "application/json"}

    def _get(self, path, params=None):
        r = requests.get(self.base + path, headers=self.headers, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _unwrap(obj, key):
        return obj.get(key, obj) if isinstance(obj, dict) else obj

    def list_offers(self, search=""):
        params = {"format":"json", "per_page":1000, "order_by":"date DESC,offer_number DESC"}
        if search: params["offer_number"] = search
        data = self._get("/offers", params)
        offers = self._unwrap(data, "offers")
        if isinstance(offers, dict): offers = offers.get("offer", [])
        return offers if isinstance(offers, list) else ([offers] if offers else [])

    def get_offer(self, offer_id):
        return self._unwrap(self._get(f"/offers/{offer_id}", {"format":"json"}), "offer")

    def get_offer_items(self, offer_id):
        data = self._get("/offer-items", {"format":"json", "offer_id":offer_id, "per_page":100})
        items = self._unwrap(data, "offer-items")
        if isinstance(items, dict): items = items.get("offer-item", [])
        return items if isinstance(items, list) else ([items] if items else [])

    def get_client(self, client_id):
        if not client_id: return {}
        return self._unwrap(self._get(f"/clients/{client_id}", {"format":"json"}), "client")

    def get_full_offer(self, offer_id):
        offer = self.get_offer(offer_id)
        offer["items"] = self.get_offer_items(offer_id)
        offer["client"] = self.get_client(offer.get("client_id"))
        return offer
