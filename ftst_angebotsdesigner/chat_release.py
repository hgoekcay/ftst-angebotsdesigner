"""One explicit release per reviewed transfer; never send a customer message.

The caller must bind the user's confirmation to the reviewed transfer snapshot.
Any claimed attempt, including a process crash, permanently prevents another PUT.
Reconciliation only reads Billomat and validates against the frozen transfer.
"""
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from quote_transfer import verify
from storage import RecordConflict

LABELS = {
    'completing': 'Freigabe begonnen – Bestätigung noch offen; nicht erneut freigeben.',
    'open': 'Leistungsvorschlag freigegeben und geprüft. Es wurde nichts versendet.',
    'uncertain': 'Freigabe nicht eindeutig bestätigt. Nur Status prüfen; keine erneute Freigabe.',
    'blocked': 'Billomat-Entwurf wurde geändert oder ist unvollständig. Bitte prüfen.',
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def update(store, identity, project_id, record, status, offer_number=''):
    def write(current, db):
        if not current or current.get('token') != record['token']:
            raise RecordConflict('Freigabestatus wurde geändert. Bitte neu laden.')
        if current['status'] == 'open':
            return current
        return dict(current, status=status, label=LABELS[status],
                    offer_number=offer_number, checked_at=now())
    return store.transact_record(identity, 'chat_release', project_id, write)


def is_open(offer, transfer):
    return (isinstance(offer, dict) and offer.get('status') == 'OPEN'
            and bool(str(offer.get('offer_number') or '').strip())
            and not verify(dict(offer, status='DRAFT'), transfer))


def reconcile(store, identity, project_id, client_api):
    record = store.record(identity, 'chat_release', project_id)
    if not record:
        raise ValueError('Für dieses Projekt wurde noch keine Freigabe begonnen.')
    try:
        offer = client_api.get_offer_for_verification(record['offer_id'])
        valid = is_open(offer, record['transfer'])
    except (RuntimeError, ValueError, TypeError, KeyError):
        # Provider exception text can contain credentials or customer data.
        valid = False
    if valid:
        return update(store, identity, project_id, record, 'open', str(offer['offer_number']).strip())
    return update(store, identity, project_id, record, 'uncertain')


def complete(store, identity, project_id, client_api):
    previous = store.record(identity, 'chat_release', project_id)
    if previous:
        return previous
    transfer = store.record(identity, 'quote_transfer', project_id)
    oid = str((transfer or {}).get('offer_id') or '')
    if not transfer or transfer.get('status') != 'created' or not oid.isdigit() or int(oid) <= 0:
        raise ValueError('Zuerst den geprüften Billomat-Entwurf anlegen.')
    try:
        draft = client_api.get_offer_for_verification(oid)
        valid = isinstance(draft, dict) and not verify(draft, transfer)
    except (RuntimeError, ValueError, TypeError, KeyError):
        raise ValueError('Billomat-Entwurf konnte nicht geprüft werden. Es wurde nichts freigegeben.') from None
    if not valid:
        raise ValueError(LABELS['blocked'])
    token = uuid.uuid4().hex

    def claim(current, db):
        if current:
            return current
        row = db.execute('SELECT payload FROM records WHERE account=? AND kind=? AND id=?',
                         (identity, 'quote_transfer', project_id)).fetchone()
        if not row or json.loads(row[0]) != transfer:
            raise RecordConflict('Der geprüfte Entwurf wurde geändert. Bitte erneut prüfen.')
        return {'token': token, 'status': 'completing', 'label': LABELS['completing'],
                    'offer_id': oid, 'offer_number': '', 'transfer': deepcopy(transfer), 'started_at': now()}

    record = store.transact_record(identity, 'chat_release', project_id, claim)
    if record['token'] != token:
        return record
    try:
        client_api._offer_request('PUT', '/offers/' + oid + '/complete', payload={'complete': {}})
    except (RuntimeError, ValueError, TypeError):
        return update(store, identity, project_id, record, 'uncertain')
    return reconcile(store, identity, project_id, client_api)

