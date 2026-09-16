"""Small, account-scoped inventory. An append-only journal is the source of truth.

Quantities are integer thousandths; reservations and movements commit together.
Only the pilot main warehouse is supported. No external writes take place.
"""
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from storage import RecordConflict, StorageError


class InventoryError(ValueError):
    pass


def quantity(value, unit, zero=False):
    try:
        n = Decimal(str(value).strip().replace(',', '.'))
        if not n.is_finite() or n < 0 or (not zero and n == 0) or n > 1000000:
            raise ValueError
        scaled = n * 1000
        if scaled != scaled.to_integral_value() or (unit == 'Stück' and n != n.to_integral_value()):
            raise ValueError
        return int(scaled)
    except (InvalidOperation, ValueError):
        raise InventoryError('Menge prüfen: Stück ganzzahlig, Meter mit höchstens drei Nachkommastellen.') from None


def fmt(n):
    return format(Decimal(n) / 1000, 'f').rstrip('0').rstrip('.').replace('.', ',') if n % 1000 else str(n // 1000)


def required(value, label, limit=300):
    result = str(value or '').strip()
    if not result or len(result) > limit:
        raise InventoryError(f'{label} fehlt oder ist zu lang.')
    return result


def reserved(state, article, except_order=None):
    return sum(o['reserved'].get(article, 0) for key, o in state['orders'].items() if key != except_order)


def open_need(order, article):
    return max(0, order['needs'].get(article, 0) - order['issued'].get(article, 0))


def reserve(state, order):
    for aid in order['needs']:
        a = state['articles'][aid]
        available = max(0, a['stock'] - reserved(state, aid, order['id'])) if a['known'] else 0
        order['reserved'][aid] = min(open_need(order, aid), available)


def incoming(state, order, article):
    return sum(p['quantity'] - p['received'] - p['cancelled'] for p in state['purchases'].values()
               if p['order'] == order and p['article'] == article)


def apply(state, action, p):
    """Deterministic projection; only validated journal commands are persisted."""
    if action == 'purchase':
        pid = required(p.get('id'), 'Bestellvorgang', 100)
        oid, aid = str(p.get('order', '')), str(p.get('article', ''))
        if pid in state['purchases']:
            raise InventoryError('Bestellvorgang bereits erfasst.')
        order = state['orders'].get(oid)
        if not order or not order['active'] or aid not in order['needs'] or not order['needs'][aid]:
            raise InventoryError('Aktiven Auftrag und benötigten Materialartikel auswählen.')
        supplier = required(p.get('supplier'), 'Lieferant')
        reference = required(p.get('reference'), 'Externe Bestellnummer / eindeutige Bestellposition')
        if p.get('ordered') != 'yes':
            raise InventoryError('Nur eine tatsächlich extern aufgegebene Bestellung erfassen.')
        if any(x['supplier'].casefold() == supplier.casefold() and x['reference'].casefold() == reference.casefold()
               and x['article'] == aid for x in state['purchases'].values()):
            raise InventoryError('Diese Lieferanten-Bestellposition ist bereits erfasst. Bei Aufteilung eine eindeutige Teilposition verwenden.')
        delivery = str(p.get('delivery', '')).strip()
        if delivery:
            try:
                date.fromisoformat(delivery)
            except ValueError:
                raise InventoryError('Lieferdatum muss ein gültiges Datum sein.') from None
        state['purchases'][pid] = dict(id=pid, order=oid, article=aid, supplier=supplier, reference=reference,
                                       quantity=quantity(p.get('quantity'), state['articles'][aid]['unit']),
                                       received=0, cancelled=0, delivery=delivery,
                                       confirmed=p.get('confirmed') == 'yes', note=str(p.get('note', ''))[:300])
        return
    if action == 'purchase_cancel':
        purchase = state['purchases'].get(str(p.get('purchase', '')))
        if not purchase:
            raise InventoryError('Bestellvorgang fehlt.')
        required(p.get('note'), 'Nachweis der extern bestätigten Stornierung')
        if p.get('confirmed') != 'yes':
            raise InventoryError('Restmenge erst nach tatsächlicher externer Stornierung ausbuchen.')
        remaining = purchase['quantity'] - purchase['received'] - purchase['cancelled']
        if remaining <= 0:
            raise InventoryError('Keine offene Restmenge vorhanden.')
        purchase['cancelled'] += remaining
        return
    if action == 'reverse':
        required(p.get('note'), 'Stornobegründung')
        event = next((e for e in state['events'] if e['id'] == p.get('event')), None)
        if not event or event['action'] not in ('receive', 'issue', 'return'):
            raise InventoryError('Nur Eingang, Entnahme oder Rückgabe können gegengebucht werden. Zählungen durch begründete neue Zählung korrigieren.')
        if any(e['action'] == 'reverse' and e['payload'].get('event') == event['id'] for e in state['events']):
            raise InventoryError('Vorgang wurde bereits gegengebucht.')
        original = event['payload']
        aid = original['article']
        a = state['articles'][aid]
        n = quantity(original['quantity'], a['unit'])
        order = state['orders'].get(original.get('order'))
        if event['action'] == 'receive':
            if a['stock'] - n < reserved(state, aid):
                raise InventoryError('Gegenbuchung würde verfügbare/reservierte Mengen unterschreiten. Folgebewegungen zuerst prüfen.')
            a['stock'] -= n
            if original.get('purchase'):
                state['purchases'][original['purchase']]['received'] -= n
        elif event['action'] == 'issue':
            if order['issued'].get(aid, 0) < n:
                raise InventoryError('Entnahme wurde bereits zurückgegeben. Folgebewegungen zuerst prüfen.')
            a['stock'] += n
            order['issued'][aid] -= n
        else:
            if a['stock'] - n < reserved(state, aid):
                raise InventoryError('Zurückgegebene Ware ist inzwischen reserviert oder entnommen.')
            a['stock'] -= n
            order['issued'][aid] = order['issued'].get(aid, 0) + n
        return
    if action == 'article':
        aid = required(p.get('id'), 'Artikel-ID', 100)
        if aid in state['articles']:
            raise InventoryError('Artikel wird bereits im Lager geführt.')
        if p.get('unit') not in ('Stück', 'm'):
            raise InventoryError('Bitte Stück oder Meter ausdrücklich zuordnen.')
        state['articles'][aid] = dict(id=aid, title=required(p.get('title'), 'Artikelname'),
                                      unit=p['unit'], stock=0, known=False)
        return
    if action == 'order':
        oid = required(p.get('id'), 'Projekt-ID', 100)
        if oid in state['orders']:
            raise InventoryError('Für dieses Projekt besteht bereits ein Auftrag.')
        needs = {}
        for line in p.get('lines', []):
            aid = str(line['article_id'])
            if aid not in state['articles']:
                raise InventoryError('Materialartikel zuerst im Lager aufnehmen.')
            needs[aid] = needs.get(aid, 0) + quantity(line['quantity'], state['articles'][aid]['unit'])
        if not needs:
            raise InventoryError('Mindestens einen Materialartikel auswählen.')
        order = dict(id=oid, title=required(p.get('title'), 'Auftrag'),
                     reference=required(p.get('reference'), 'Auftragsnachweis'),
                     quote_revision=p['quote_revision'], needs=needs, reserved={}, issued={}, active=True)
        state['orders'][oid] = order
        reserve(state, order)
        return
    oid = str(p.get('order', ''))
    order = state['orders'].get(oid)
    if action in ('reserve', 'release', 'cancel', 'need'):
        if not order or not order['active']:
            raise InventoryError('Aktiven Auftrag auswählen.')
        if action == 'cancel':
            order['active'] = False
            order['reserved'] = {}
        elif action == 'release':
            required(p.get('note'), 'Begründung')
            order['reserved'] = {}
        elif action == 'reserve':
            reserve(state, order)
        else:
            aid = str(p.get('article', ''))
            if aid not in state['articles']:
                raise InventoryError('Artikel fehlt.')
            n = quantity(p.get('quantity'), state['articles'][aid]['unit'], zero=True)
            if n < order['issued'].get(aid, 0):
                raise InventoryError('Bedarf liegt unter bereits entnommener Menge. Zuerst Rückgabe prüfen.')
            required(p.get('note'), 'Begründung')
            order['needs'][aid] = n
            # Do not allocate newly available stock silently during a demand edit.
            order['reserved'][aid] = min(order['reserved'].get(aid, 0), open_need(order, aid))
        return
    aid = str(p.get('article', ''))
    a = state['articles'].get(aid)
    if not a:
        raise InventoryError('Lagerartikel auswählen.')
    n = quantity(p.get('quantity'), a['unit'], zero=action in ('opening', 'count'))
    if action == 'opening':
        if a['known']:
            raise InventoryError('Anfangsbestand bereits erfasst. Zählkorrektur verwenden.')
        a.update(stock=n, known=True)
    elif not a['known']:
        raise InventoryError('Bestand unbekannt. Zuerst tatsächlich zählen und Anfangsbestand erfassen.')
    elif action == 'receive':
        if p.get('purchase'):
            purchase = state['purchases'].get(p['purchase'])
            if not purchase or purchase['article'] != aid:
                raise InventoryError('Bestellvorgang passt nicht zum Artikel.')
            if n > purchase['quantity'] - purchase['received'] - purchase['cancelled']:
                raise InventoryError('Wareneingang überschreitet die offene Bestellmenge.')
            purchase['received'] += n
        a['stock'] += n
    elif action == 'count':
        required(p.get('note'), 'Begründung')
        if n < reserved(state, aid):
            raise InventoryError('Zählbestand unterschreitet Reservierungen. Betroffene Aufträge zuerst prüfen und Reservierungen freigeben.')
        a['stock'] = n
    elif action == 'issue':
        if not order or not order['active']:
            raise InventoryError('Aktiven Auftrag auswählen.')
        if n > open_need(order, aid):
            raise InventoryError('Entnahme überschreitet den offenen Bedarf. Bedarf zuerst begründet ändern.')
        if n > a['stock'] - reserved(state, aid, oid):
            raise InventoryError('Nicht genug frei verfügbares Material. Andere Auftragsreservierungen bleiben geschützt.')
        a['stock'] -= n
        order['issued'][aid] = order['issued'].get(aid, 0) + n
        order['reserved'][aid] = max(0, order['reserved'].get(aid, 0) - n)
    elif action == 'return':
        if not order or n > order['issued'].get(aid, 0):
            raise InventoryError('Rückgabe überschreitet die netto entnommene Auftragsmenge.')
        if p.get('usable') != 'yes':
            raise InventoryError('Nur geprüfte, verwendbare Ware zurückbuchen. Defekte Ware bleibt außerhalb des verfügbaren Hauptlagers.')
        a['stock'] += n
        order['issued'][aid] -= n
    else:
        raise InventoryError('Unbekannte Lageraktion.')


def project(journal):
    if journal is None:
        journal = {'version': 1, 'events': []}
    if journal.get('version') != 1 or not isinstance(journal.get('events'), list):
        raise StorageError('Unbekannte Lagerdatenversion.')
    state = {'articles': {}, 'orders': {}, 'purchases': {}, 'events': [], 'revision': len(journal['events'])}
    try:
        for event in journal['events']:
            apply(state, event['action'], event['payload'])
            state['events'].append(event)
    except (KeyError, TypeError, ValueError) as exc:
        raise StorageError('Lagerjournal ist nicht lesbar. Keine Buchung wurde verändert.') from exc
    return state


def load(store, account):
    return project(store.record(account, 'inventory', 'main'))


def execute(store, account, action, payload, operation, actor, expected, verify=None):
    operation = required(operation, 'Vorgangs-ID', 100)
    actor = required(actor, 'Verantwortliche Person', 100)
    digest = hashlib.sha256(json.dumps([action, payload, actor], sort_keys=True).encode()).hexdigest()

    def change(journal, db):
        journal = journal or {'version': 1, 'events': []}
        state = project(journal)
        for event in journal['events']:
            if event['id'] == operation:
                if event['digest'] != digest:
                    raise RecordConflict('Vorgangs-ID wurde bereits für andere Eingaben verwendet.')
                return journal
        if str(expected) != str(state['revision']):
            raise RecordConflict('Lagerdaten wurden inzwischen geändert. Bitte neu laden und erneut prüfen.')
        if verify:
            verify(db)
        apply(state, action, payload)
        journal['events'].append(dict(id=operation, action=action, payload=payload, actor=actor,
                                      digest=digest, at=datetime.now(timezone.utc).isoformat()))
        return journal

    return project(store.transact_record(account, 'inventory', 'main', change))


def procurement(state, order_id):
    order = state['orders'][order_id]
    if not order['active']:
        return []
    result = []
    for aid in order['needs']:
        a = state['articles'][aid]
        missing = max(0, open_need(order, aid) - order['reserved'].get(aid, 0))
        if missing:
            ordered = incoming(state, order_id, aid)
            result.append(dict(article=aid, title=a['title'], unit=a['unit'], quantity=missing,
                               incoming=ordered, to_buy=max(0, missing-ordered),
                               status='Beschaffung prüfen' if a['known'] else 'Zuerst Bestand zählen',
                               stock_known=a['known']))
    return result
