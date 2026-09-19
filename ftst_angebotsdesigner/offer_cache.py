"""Persistent recent-offer summaries, refreshed by one bounded background worker."""
import threading
import time
from urllib.parse import urlencode
from datetime import datetime, timezone

INTERVAL = 300
RETRY = 60
FIELDS = ('id', 'offer_number', 'number', 'date', 'title', 'total_gross')


class OfferCache:
    def __init__(self, store, account, client):
        self.store, self.account, self.client = store, account, client
        self.lock = threading.Lock()
        self.thread = None
        self.stop = threading.Event()

    def snapshot(self):
        return self.store.record(self.account, 'offer_list', 'recent') or {}

    def refresh(self):
        previous = self.snapshot()
        now = time.time()
        try:
            rows = self.client.list_offers()
            if not isinstance(rows, list) or len(rows) > 30 or any(
                    not isinstance(row, dict) or not str(row.get('id', '')).isdigit() for row in rows):
                raise ValueError('Invalid offer summaries')
            value = {'rows': [{k: row.get(k) for k in FIELDS} for row in rows],
                     'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                     'checked': now, 'error': False}
        except Exception:
            # Keep the last successful snapshot; never persist credentials or raw API errors.
            value = dict(previous, checked=now, error=True)
        self.store.put_record(self.account, 'offer_list', 'recent', value)
        return value

    def run(self):
        while not self.stop.is_set():
            try:
                value = self.snapshot()
                delay = RETRY if value.get('error') else INTERVAL
                remaining = delay - (time.time() - value.get('checked', 0))
                if remaining <= 0 or remaining > delay:
                    value = self.refresh()
                    remaining = RETRY if value.get('error') else INTERVAL
            except Exception:
                remaining = RETRY
            self.stop.wait(remaining)

    def start(self):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, daemon=True, name='recent-offers')
                self.thread.start()


_guard = threading.Lock()
_workers = {}


def worker(store, account, client):
    key = (str(store.path), account)
    with _guard:
        if key not in _workers:
            _workers[key] = OfferCache(store, account, client)
        return _workers[key]


def page(request, store, account, client, base, ingress, clean, money, date_de):
    try:
        number = int(request.args.get('page', '1'))
        if not 1 <= number <= 10000:
            raise ValueError
    except ValueError:
        return base('Angebote', '<div class="card"><h1>Ungültige Angebotsseite</h1></div>'), 400
    search = request.args.get('search', '').strip()[:100]
    cache = worker(store, account, client)
    cache.start()
    refresh = ''
    if number == 1 and not search:
        snapshot = cache.snapshot()
        data = snapshot.get('rows', [])
        if snapshot.get('updated_at'):
            note = 'Letzte 30 Angebote · gespeicherter Stand: ' + clean(snapshot['updated_at'])
            if snapshot.get('error'):
                note += ' · Aktualisierung derzeit nicht möglich. Gespeicherte Angebote bleiben verfügbar.'
            else:
                note += ' · Automatische Aktualisierung alle 5 Minuten.'
        else:
            note = 'Die letzten 30 Angebote werden erstmals im Hintergrund geladen.'
            if snapshot.get('error'):
                note = 'Billomat derzeit nicht erreichbar. Automatischer neuer Versuch in einer Minute.'
            refresh = '<meta http-equiv="refresh" content="10">'
    else:
        try:
            data = client.list_offers(search, page=number)
            note = f'Seite {number} · bis zu 30 Angebote direkt aus Billomat'
        except Exception:
            return base('Angebote', '<div class="card"><h1>Billomat derzeit nicht erreichbar</h1><p>Bitte später erneut versuchen.</p><a class="btn" href="' + ingress('offers') + '">Gespeicherte Angebote</a></div>'), 502
    rows = ''.join('<tr><td data-label="Nr."><b>' + clean(o.get('offer_number') or o.get('number') or '-') +
                   '</b></td><td data-label="Datum">' + clean(date_de(o.get('date'))) +
                   '</td><td data-label="Titel">' + clean(o.get('title') or '-') +
                   '</td><td data-label="Brutto" class="money">' + money(o.get('total_gross')) +
                   '</td><td><a class="btn" href="' + ingress('offer/' + str(o['id'])) + '">Öffnen</a></td></tr>' for o in data)
    links = ''
    if number > 1 or search:
        links += '<a class="btn light" href="' + ingress('offers') + '">Neueste Angebote</a>'
    if number > 1:
        links += '<a class="btn light" href="' + ingress('offers') + '?' + clean(urlencode({'page': number-1, 'search': search})) + '">Vorherige Seite</a>'
    if len(data) == 30:
        links += '<a class="btn light" href="' + ingress('offers') + '?' + clean(urlencode({'page': number+1, 'search': search})) + '">Weitere 30 Angebote</a>'
    form = '<form method="get"><label for="offer-search">Angebotsnummer suchen</label><input id="offer-search" name="search" value="' + clean(search) + '"><button class="btn">Suchen</button></form>'
    return base('Angebote', refresh + '<div class="card"><div class="eyebrow">Billomat</div><h1>Ihre Angebote</h1><p class="muted">' + note + '</p>' + form +
                '<table><thead><tr><th>Nr.</th><th>Datum</th><th>Titel</th><th>Brutto</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>' +
                ('<p>Keine Angebote auf dieser Seite.</p>' if not data and not refresh else '') + links + '</div>')
